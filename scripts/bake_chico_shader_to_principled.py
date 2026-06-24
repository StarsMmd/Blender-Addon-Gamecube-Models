"""Standalone Blender script: bake custom shader-group materials down to a
Principled BSDF so the exporter can read their composited albedo.

Some rips (notably models using the `PokemonShaderbyChicoEevee` shader pack)
drive the Material Output's Surface from a custom `ShaderNodeGroup`. The real
surface colour is NOT the raw albedo texture: it is the albedo modulated by a
layer-mask texture that selects between several flat base-colour layers, plus
eye / emission compositing. Wiring the raw `Albedo` input straight into a
Principled BSDF (an earlier approach) drops all of that recolouring, so the
model exports washed-out and renders wrong in-game.

The chico shader is built for baking: its group exposes a dedicated
`BaseColorBake` output socket whose Principled BSDF carries the fully
composited surface colour. This script bakes that output to a new per-material
image and feeds the baked image into a clean Principled BSDF that the exporter
can resolve as a normal albedo texture.

For each convertible material it:
  1. Creates a packed image sized to the source albedo texture.
  2. Bakes the group's `BaseColorBake` diffuse colour into it (one Cycles
     pass over every contributing mesh, so materials shared across objects
     keep all their UV islands).
  3. Bakes the albedo alpha into the image's alpha channel (cutout/eyes).
  4. Builds a fresh Principled BSDF fed by the baked image and connects it to
     the Material Output. The original group is left in place but disconnected
     from the output, so the change is easy to inspect or undo.

Run it from Blender's Scripting panel before exporting. Run it AFTER
`prepare_for_pkx_export.py` is fine; run it on the un-prepped model too.

Idempotent: a material whose Surface is already a Principled BSDF is skipped.

This script is fully standalone — no imports from the plugin codebase. The
only allowed imports are `bpy`, `math`, and Python stdlib.
"""
import bpy
import math


# Output socket name on the shader group that carries the composited,
# bake-ready base colour. Matched after normalisation (see `_normalise`).
_BAKE_OUTPUT_KEYS = ("basecolorbake", "basecolour bake", "albedobake", "colorbake")
# Group input that carries the cutout / albedo alpha, best match first.
_ALPHA_INPUT_KEYS = ("albedoalpha", "basecoloralpha", "alpha")

_DEFAULT_SIZE = 1024
_BAKE_MARGIN = 16


def _normalise(name):
    return name.lower().replace("_", "").replace(" ", "")


def _match(name, keys):
    n = _normalise(name)
    for i, key in enumerate(keys):
        if _normalise(key) in n:
            return i
    return len(keys)


def _surface_node(node_tree):
    out = next((n for n in node_tree.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None or not out.inputs["Surface"].is_linked:
        return None, None
    return out, out.inputs["Surface"].links[0].from_node


def _bake_output_socket(group_node):
    """Return the group's bake-ready colour output socket, or None."""
    if group_node.type != "GROUP" or group_node.node_tree is None:
        return None
    best, best_rank = None, len(_BAKE_OUTPUT_KEYS)
    for sock in group_node.outputs:
        r = _match(sock.name, _BAKE_OUTPUT_KEYS)
        if r < best_rank:
            best, best_rank = sock, r
    return best


def _alpha_input_socket(group_node):
    best, best_rank = None, len(_ALPHA_INPUT_KEYS)
    for sock in group_node.inputs:
        r = _match(sock.name, _ALPHA_INPUT_KEYS)
        if r < best_rank:
            best, best_rank = sock, r
    return best if best_rank < len(_ALPHA_INPUT_KEYS) else None


def _albedo_props(group_node):
    """Source albedo size + wrap/filter, for matching the bake target.

    Returns (width, height, extension, interpolation). The model samples the
    albedo (and layer mask) with REPEAT wrap and UVs that climb past 1.0
    (UDIM-style stacking), so the baked tile must carry the same extension for
    the exporter to re-tile it correctly.
    """
    w, h = _DEFAULT_SIZE, _DEFAULT_SIZE
    ext, interp = "REPEAT", "Linear"
    for sock in group_node.inputs:
        if _match(sock.name, ("albedo", "basecolor")) == 0 and sock.is_linked:
            src = sock.links[0].from_node
            if src.type == "TEX_IMAGE":
                ext, interp = src.extension, src.interpolation
                if src.image and tuple(src.image.size) != (0, 0):
                    w, h = int(src.image.size[0]), int(src.image.size[1])
            break
    return w, h, ext, interp


def _render_uv_layer(mesh):
    if not mesh.uv_layers:
        return None
    for layer in mesh.uv_layers:
        if layer.active_render:
            return layer
    return mesh.uv_layers.active


def _collapse_uvs_to_tile(obj):
    """Shift every face into the base UV tile by an integer offset.

    The model stacks UV islands across tiles (V > 1) and relies on REPEAT to
    sample one 512-tall albedo. Cycles bakes at literal UVs, so islands above
    the [0,1] tile would miss the bake target. Shifting per face (not per
    vertex) by floor(centroid) keeps each island intact while landing it in
    the base tile, where the composite — periodic under REPEAT — is identical.
    Returns (layer_name, original_uv_array) for restoration, or None.
    """
    me = obj.data
    layer = _render_uv_layer(me)
    if layer is None:
        return None
    data = layer.data
    saved = [0.0] * (len(data) * 2)
    data.foreach_get("uv", saved)
    for poly in me.polygons:
        loops = poly.loop_indices
        n = len(loops)
        cu = sum(data[l].uv[0] for l in loops) / n
        cv = sum(data[l].uv[1] for l in loops) / n
        ox, oy = math.floor(cu), math.floor(cv)
        if ox or oy:
            for l in loops:
                uv = data[l].uv
                uv[0] -= ox
                uv[1] -= oy
    return (layer.name, saved)


def _restore_uvs(obj, saved):
    if saved is None:
        return
    name, arr = saved
    layer = obj.data.uv_layers.get(name)
    if layer is not None:
        layer.data.foreach_set("uv", arr)
        obj.data.update()


def _objects_using(mat):
    objs = []
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        if any(sl.material is mat for sl in ob.material_slots):
            objs.append(ob)
    return objs


def _new_image(name, w, h, is_data):
    img = bpy.data.images.new(name, width=w, height=h, alpha=True, float_buffer=False)
    img.colorspace_settings.name = "Non-Color" if is_data else "sRGB"
    return img


def _add_target_node(nt, image, location):
    node = nt.nodes.new("ShaderNodeTexImage")
    node.image = image
    node.location = location
    nt.nodes.active = node          # bake writes to the active image node
    for n in nt.nodes:
        n.select = False
    node.select = True
    return node


def _configure_cycles(scene, bake_type):
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    bake = scene.render.bake
    bake.use_selected_to_active = False
    bake.margin = _BAKE_MARGIN
    bake.use_clear = True
    if bake_type == "DIFFUSE":
        bake.use_pass_direct = False
        bake.use_pass_indirect = False
        bake.use_pass_color = True


def _select_for_bake(objects):
    for ob in bpy.data.objects:
        ob.select_set(False)
    active = None
    for ob in objects:
        try:
            ob.hide_set(False)
        except RuntimeError:
            pass
        ob.hide_render = False
        ob.select_set(True)
        active = ob
    bpy.context.view_layer.objects.active = active
    return active


def _copy_red_to_alpha(color_img, alpha_img):
    """Move the red channel of `alpha_img` into the alpha of `color_img`."""
    n = color_img.size[0] * color_img.size[1]
    col = [0.0] * (n * 4)
    alp = [0.0] * (n * 4)
    color_img.pixels.foreach_get(col)
    alpha_img.pixels.foreach_get(alp)
    for i in range(n):
        col[i * 4 + 3] = alp[i * 4]
    color_img.pixels.foreach_set(col)
    color_img.update()


def _collect_jobs():
    """Find convertible materials and snapshot what each bake needs."""
    jobs = []
    skipped_principled = 0
    skipped_other = []
    seen = set()
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        for sl in ob.material_slots:
            mat = sl.material
            if mat is None or mat in seen or not mat.use_nodes or mat.node_tree is None:
                continue
            seen.add(mat)
            out, surface = _surface_node(mat.node_tree)
            if surface is None:
                continue
            if surface.type == "BSDF_PRINCIPLED":
                skipped_principled += 1
                continue
            # The bake output is an output socket on the group node; its data
            # comes from a link INSIDE the group, so it is not (and need not
            # be) linked downstream in the material tree.
            bake_sock = _bake_output_socket(surface)
            if bake_sock is None:
                skipped_other.append(mat.name)
                continue
            w, h, ext, interp = _albedo_props(surface)
            jobs.append({
                "mat": mat, "output": out, "group": surface,
                "bake_sock": bake_sock, "alpha_in": _alpha_input_socket(surface),
                "w": w, "h": h, "ext": ext, "interp": interp,
                "objs": _objects_using(mat),
            })
    return jobs, skipped_principled, skipped_other


def _setup_color_pass(job):
    nt = job["mat"].node_tree
    img = _new_image(job["mat"].name + "_bake", job["w"], job["h"], is_data=False)
    job["color_img"] = img
    job["color_node"] = _add_target_node(
        nt, img, (job["group"].location.x + 400, job["group"].location.y))
    nt.links.new(job["bake_sock"], job["output"].inputs["Surface"])


def _setup_alpha_pass(job):
    """Route the albedo alpha into an emission surface and a data target.

    Returns True if an alpha pass is needed for this material.
    """
    alpha_in = job["alpha_in"]
    if alpha_in is None or not alpha_in.is_linked:
        return False
    nt = job["mat"].node_tree
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.location = (job["group"].location.x, job["group"].location.y - 300)
    emit.inputs["Strength"].default_value = 1.0
    nt.links.new(alpha_in.links[0].from_socket, emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], job["output"].inputs["Surface"])
    img = _new_image(job["mat"].name + "_bake_a", job["w"], job["h"], is_data=True)
    job["alpha_img"] = img
    job["alpha_node"] = _add_target_node(
        nt, img, (job["group"].location.x + 400, job["group"].location.y - 300))
    job["alpha_emit"] = emit
    return True


def _finalize(job):
    nt = job["mat"].node_tree
    has_alpha = "alpha_img" in job
    if has_alpha:
        _copy_red_to_alpha(job["color_img"], job["alpha_img"])
        # Tear down the temporary alpha bake graph.
        nt.nodes.remove(job["alpha_emit"])
        nt.nodes.remove(job["alpha_node"])
        bpy.data.images.remove(job["alpha_img"])

    job["color_img"].pack()

    # Match the source albedo's wrap/filter so the exporter re-tiles the baked
    # base tile across the model's stacked (V > 1) UVs.
    job["color_node"].extension = job["ext"]
    job["color_node"].interpolation = job["interp"]

    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (job["group"].location.x + 400, job["group"].location.y - 200)
    nt.links.new(job["color_node"].outputs["Color"], bsdf.inputs["Base Color"])
    if has_alpha:
        nt.links.new(job["color_node"].outputs["Alpha"], bsdf.inputs["Alpha"])
        try:
            job["mat"].blend_method = "CLIP"
        except (AttributeError, TypeError):
            pass
    nt.links.new(bsdf.outputs["BSDF"], job["output"].inputs["Surface"])


def convert_all():
    jobs, skipped_principled, skipped_other = _collect_jobs()
    if not jobs:
        return [], skipped_principled, skipped_other

    scene = bpy.context.scene
    saved = (scene.render.engine,)
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    all_objs = []
    for job in jobs:
        _setup_color_pass(job)
        for ob in job["objs"]:
            if ob not in all_objs:
                all_objs.append(ob)

    # Collapse stacked UV tiles into the base tile for the duration of the
    # bakes, then restore the original UVs so the exported mesh keeps its
    # REPEAT-tiled coordinates.
    saved_uvs = [(ob, _collapse_uvs_to_tile(ob)) for ob in all_objs]
    try:
        _configure_cycles(scene, "DIFFUSE")
        _select_for_bake(all_objs)
        bpy.ops.object.bake(type="DIFFUSE")

        alpha_jobs = [job for job in jobs if _setup_alpha_pass(job)]
        if alpha_jobs:
            alpha_objs = []
            for job in alpha_jobs:
                for ob in job["objs"]:
                    if ob not in alpha_objs:
                        alpha_objs.append(ob)
            _configure_cycles(scene, "EMIT")
            _select_for_bake(alpha_objs)
            bpy.ops.object.bake(type="EMIT")
    finally:
        for ob, snapshot in saved_uvs:
            _restore_uvs(ob, snapshot)

    for job in jobs:
        _finalize(job)

    scene.render.engine = saved[0]
    return [job["mat"].name for job in jobs], skipped_principled, skipped_other


if __name__ == "__main__" or True:
    print("=== Bake custom-shader materials to Principled BSDF ===")
    converted, already, other = convert_all()
    print("  Baked %d material(s) to a Principled BSDF surface:" % len(converted))
    for name in converted:
        print("    %s" % name)
    if already:
        print("  Skipped %d material(s) already using a Principled BSDF" % already)
    if other:
        print("  No bake output found on %d material(s) (left unchanged): %s"
              % (len(other), ", ".join(other)))
    print("=== Done ===")
