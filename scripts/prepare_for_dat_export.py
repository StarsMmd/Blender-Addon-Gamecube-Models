"""Standalone Blender script: Prepare a scene for bare `.dat` export.

Run this from Blender's Scripting panel (Text Editor > Run Script) before
exporting a model that does NOT carry a PKX header (e.g. map sections,
effect archives, anything where the output extension is `.dat` rather
than `.pkx`).

The script operates on all objects in the scene — no selection required:
  1. Bakes loc/rot/scale on all armatures and their child meshes so
     `matrix_world` is identity. The exporter rejects unbaked transforms
     because the SRT decomposition of bone matrices loses any shear that
     a non-uniform armature scale combined with edit-bone rotation would
     introduce, drifting bones away from mesh vertices the further you
     walk down the bone chain.
  2. Stamps a default `dat_camera_aspect` on any scene camera missing one
     (camera creation lives in scripts/add_debug_camera.py)
  3. Limits vertex bone weights to 3 per vertex (GameCube hardware
     constraint) and quantises to 10% steps
  4. Culls unused material slots so EEVEE doesn't compile materials no
     polygon references
  5. Downscales textures larger than 512×512 proportionally
  6. Auto-selects a GX texture format for any image left on AUTO

After running, the scene can be exported via File > Export > Gamecube
model (.dat).

For PKX/Pokémon exports — which additionally need a PKX header with
animation slots, body map, derived timings, shiny filter shader nodes,
and battle-light preview — use `scripts/prepare_for_pkx_export.py`
instead. That script is a superset of this one's responsibilities.

This script is fully standalone — no imports from the plugin codebase
or from `prepare_for_pkx_export.py`. The shared helpers are duplicated
on purpose so each script can be reasoned about in isolation.
"""
import bpy


# ---------------------------------------------------------------------------
# Bake transforms
# ---------------------------------------------------------------------------
#
# The exporter requires every armature and every mesh parented to one to
# have identity `matrix_world`. Without this, `describe_skeleton` ends up
# decomposing a sheared root-bone world matrix into SRT, silently dropping
# the shear, while `describe_meshes` keeps the same shear baked into vertex
# coordinates via a plain matmul. The two paths then disagree about where
# every bone-skinned vertex sits — small near the root, growing the deeper
# the bone chain goes. Baking transforms upfront via Blender's own
# `transform_apply` removes the asymmetry at its source.

def _is_identity_matrix(m, tol=1e-5):
    """Mirrors the export-side validator's tolerance check so a successful
    bake here cannot fail validation there."""
    for i in range(4):
        for j in range(4):
            expected = 1.0 if i == j else 0.0
            if abs(m[i][j] - expected) > tol:
                return False
    return True


def _apply_world_to_data(obj, world):
    """Bake `world` into obj's data (vertex coords for meshes, bone
    head/tail/roll for armatures). Resolves multi-user data by copying
    the datablock first. Does not touch obj.matrix_basis.

    Both `Mesh.transform()` and `Armature.transform()` are direct data-
    level operations — they don't go through bpy.ops, don't require the
    object to be selected/active/visible, and don't need any particular
    context. Critically for armatures, `Armature.transform()` correctly
    scales bone lengths along with head positions; the alternative
    edit-mode `bone.matrix = world @ bone.matrix` approach leaves lengths
    unchanged, which on a small-scale rig collapses the whole skeleton
    into a tiny region.

    Returns True if data was mutated, False if obj has no applicable data.
    """
    if obj.type == 'MESH':
        if obj.data is None:
            return False
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        obj.data.transform(world)
        return True
    elif obj.type == 'ARMATURE':
        if obj.data is None:
            return False
        if obj.data.users > 1:
            obj.data = obj.data.copy()
        obj.data.transform(world)
        return True
    return False


def _ensure_bone_marker_object():
    """Create (or reuse) a 1 cm octahedron object used as the
    `custom_shape` for every pose bone post-bake. Mirrors the default
    OCTAHEDRAL bone display look ("diamondy" shape) but at a fixed 1×1×1
    cm size that does not scale with bone length. The mesh isn't linked
    into any collection — it just needs to exist as a datablock for
    `pose_bone.custom_shape` to reference. Reused across runs by name."""
    name = 'DATPlugin_BoneMarker'
    obj = bpy.data.objects.get(name)
    if obj is not None:
        return obj
    mesh = bpy.data.meshes.get(name)
    if mesh is None or not mesh.vertices:
        if mesh is None:
            mesh = bpy.data.meshes.new(name)
        s = 0.005
        verts = [
            ( s, 0, 0), (-s, 0, 0),
            (0,  s, 0), (0, -s, 0),
            (0, 0,  s), (0, 0, -s),
        ]
        faces = [
            (0, 2, 4), (0, 4, 3), (0, 3, 5), (0, 5, 2),
            (1, 4, 2), (1, 3, 4), (1, 5, 3), (1, 2, 5),
        ]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
    return bpy.data.objects.new(name, mesh)


def _collect_armature_actions(arm):
    """Actions that this armature's animation_data references — active +
    every NLA strip's action. We only scale fcurves on these, not on
    every action in bpy.data.actions, so a second armature's actions
    don't get over-scaled when its scale factor differs."""
    if not arm.animation_data:
        return set()
    actions = set()
    if arm.animation_data.action:
        actions.add(arm.animation_data.action)
    for tr in arm.animation_data.nla_tracks:
        for st in tr.strips:
            if st.action:
                actions.add(st.action)
    return actions


def bake_transforms():
    """Bake loc/rot/scale on every armature and its child meshes so each
    `matrix_world` is identity.

    The naive approach (apply world matrix to data, set matrix_basis to I)
    is *almost* right but breaks animations in two non-obvious ways:

      1. `Armature.transform()` while the action is evaluating leaves the
         pose-matrix cache stale — even after view_layer.update(), pose
         evaluation reads the old rest matrix and produces wildly wrong
         bone positions. Fix: mute the action and reset all pose-bone TRS
         to identity *before* baking, restore *after*.

      2. PoseBone.location values are in bone-local rest-frame coordinates.
         Pre-bake, the bone's rest frame is scaled by the armature's world
         scale; a pose-loc of 50 on a scale-0.01 rig means 0.5 m of world
         translation. Post-bake the rest frame has scale 1.0; the same 50
         now means 50 m. Fix: multiply every pose.bones[].location fcurve
         keyframe by the armature's pre-bake scale factor. Pose rotations
         and scales are dimensionless and need no adjustment.

    Also handles per-view-layer hidden objects (`hide_get() == True`) by
    temporarily unhiding them, since several Blender ops — and even
    `Armature.transform()` in some contexts — silently no-op on objects
    that aren't `visible_get()`.

    Returns the number of objects baked.
    """
    from mathutils import Matrix as _Matrix
    import re

    armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE']
    if not armatures:
        return 0

    saved_anim = []
    saved_hide = []
    for arm in armatures:
        ad = arm.animation_data
        anim_snapshot = {
            'arm': arm,
            'scale': arm.matrix_world.to_scale().x,
            'actions': _collect_armature_actions(arm),
            'action': ad.action if ad else None,
            'use_nla': ad.use_nla if ad else None,
            'pose': [
                (pb.name,
                 pb.location.copy(),
                 pb.rotation_quaternion.copy(),
                 pb.rotation_euler.copy(),
                 pb.rotation_axis_angle[:],
                 pb.scale.copy())
                for pb in arm.pose.bones
            ],
        }
        saved_anim.append(anim_snapshot)
        if ad:
            ad.action = None
            ad.use_nla = False
        for pb in arm.pose.bones:
            pb.location = (0, 0, 0)
            pb.rotation_quaternion = (1, 0, 0, 0)
            pb.rotation_euler = (0, 0, 0)
            pb.rotation_axis_angle = (0, 0, 1, 0)
            pb.scale = (1, 1, 1)

    for arm in armatures:
        if arm.hide_get():
            saved_hide.append((arm, True))
            arm.hide_set(False)
        for obj in bpy.data.objects:
            if obj.parent is arm and obj.type == 'MESH' and obj.hide_get():
                saved_hide.append((obj, True))
                obj.hide_set(False)

    bpy.context.view_layer.update()

    targets = []
    for arm in armatures:
        targets.append((arm, arm.matrix_world.copy()))
        for obj in bpy.data.objects:
            if obj.parent is arm and obj.type == 'MESH':
                targets.append((obj, obj.matrix_world.copy()))

    baked = 0
    identity = _Matrix.Identity(4)
    for obj, world in targets:
        if _is_identity_matrix(world):
            obj.matrix_basis = identity
            if obj.parent is not None:
                obj.matrix_parent_inverse = identity
            continue
        if not _apply_world_to_data(obj, world):
            continue
        obj.matrix_basis = identity
        if obj.parent is not None:
            obj.matrix_parent_inverse = identity
        baked += 1

    bone_marker = _ensure_bone_marker_object()
    for arm in armatures:
        for pb in arm.pose.bones:
            pb.custom_shape = bone_marker
            pb.use_custom_shape_bone_size = False
            pb.custom_shape_scale_xyz = (1.0, 1.0, 1.0)

    loc_re = re.compile(r'^pose\.bones\[".*"\]\.location$')
    for snap in saved_anim:
        s = snap['scale']
        if abs(s - 1.0) < 1e-6:
            continue
        for action in snap['actions']:
            for fc in action.fcurves:
                if not loc_re.match(fc.data_path):
                    continue
                for kp in fc.keyframe_points:
                    kp.co.y *= s
                    kp.handle_left.y *= s
                    kp.handle_right.y *= s
        snap['pose'] = [
            (name, (loc[0]*s, loc[1]*s, loc[2]*s), quat, eul, aa, scl)
            for (name, loc, quat, eul, aa, scl) in snap['pose']
        ]

    for snap in saved_anim:
        arm = snap['arm']
        ad = arm.animation_data
        if ad:
            ad.action = snap['action']
            if snap['use_nla'] is not None:
                ad.use_nla = snap['use_nla']
        for (name, loc, quat, eul, aa, scl) in snap['pose']:
            pb = arm.pose.bones.get(name)
            if pb is None:
                continue
            pb.location = loc
            pb.rotation_quaternion = quat
            pb.rotation_euler = eul
            pb.rotation_axis_angle = aa
            pb.scale = scl

    for obj, _was_hidden in saved_hide:
        obj.hide_set(True)

    bpy.context.view_layer.update()

    offenders = [
        obj.name for obj, _ in targets
        if not _is_identity_matrix(obj.matrix_world)
    ]
    if offenders:
        raise RuntimeError(
            "Failed to bake transforms to identity on: "
            + ", ".join(offenders) + ". The object's data may be linked "
            "from another .blend, or its data is None. Open the offending "
            "object in the Outliner to investigate."
        )

    return baked


# ---------------------------------------------------------------------------
# Camera aspect
# ---------------------------------------------------------------------------
#
# This script does not create any camera. Use `scripts/add_debug_camera.py`
# if you want a viewport-friendly preview camera; the exporter writes
# whatever cameras are present in the scene with no special filtering.

def normalize_camera_aspect():
    """Stamp a default `dat_camera_aspect=1.18` on any scene camera that
    doesn't carry one already, so the exporter's CObj writes a sensible
    aspect for cameras authored without going through the importer.
    Returns the number of cameras touched.
    """
    touched = 0
    for obj in bpy.data.objects:
        if obj.type == 'CAMERA' and "dat_camera_aspect" not in obj:
            obj["dat_camera_aspect"] = 1.18
            print("  Camera '%s': set dat_camera_aspect = 1.18" % obj.name)
            touched += 1
    return touched


# ---------------------------------------------------------------------------
# Mesh weight limiting
# ---------------------------------------------------------------------------

MAX_WEIGHTS_PER_VERTEX = 3


def prepare_mesh_weights(armature):
    """Limit per-vertex bone influences to MAX_WEIGHTS_PER_VERTEX and
    quantise weights to 10% steps (matching game-model precision).

    Returns (weights_limited, 0) — the second value is reserved for the
    rigid-split count that the PKX prep script reports.
    """
    bone_names = {b.name for b in armature.data.bones}
    meshes = [obj for obj in bpy.data.objects
              if obj.type == 'MESH' and obj.parent == armature]

    total_limited = 0

    for mesh_obj in meshes:
        bpy.ops.object.select_all(action='DESELECT')
        mesh_obj.select_set(True)
        bpy.context.view_layer.objects.active = mesh_obj

        affected = 0
        for v in mesh_obj.data.vertices:
            bone_groups = [g for g in v.groups
                           if g.group < len(mesh_obj.vertex_groups)
                           and mesh_obj.vertex_groups[g.group].name in bone_names
                           and g.weight > 0.0]
            if len(bone_groups) > MAX_WEIGHTS_PER_VERTEX:
                affected += 1

        if affected > 0:
            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
            bpy.ops.object.vertex_group_limit_total(limit=MAX_WEIGHTS_PER_VERTEX)
            bpy.ops.object.mode_set(mode='OBJECT')
            total_limited += affected
            print("    %s: limited %d vertices to %d weights" %
                  (mesh_obj.name, affected, MAX_WEIGHTS_PER_VERTEX))

        bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
        bpy.ops.object.vertex_group_normalize_all(lock_active=False)
        bpy.ops.object.mode_set(mode='OBJECT')

        mesh_data = mesh_obj.data
        quantized = 0
        for v in mesh_data.vertices:
            for g in v.groups:
                if g.group < len(mesh_obj.vertex_groups):
                    if mesh_obj.vertex_groups[g.group].name in bone_names:
                        q = round(g.weight, 1)
                        if abs(q - g.weight) > 0.001:
                            g.weight = q
                            quantized += 1

        if quantized > 0:
            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
            bpy.ops.object.vertex_group_normalize_all(lock_active=False)
            bpy.ops.object.mode_set(mode='OBJECT')
            for v in mesh_data.vertices:
                for g in v.groups:
                    if g.group < len(mesh_obj.vertex_groups):
                        if mesh_obj.vertex_groups[g.group].name in bone_names:
                            g.weight = round(g.weight, 1)
            print("    %s: quantized %d weight values to 10%% steps" %
                  (mesh_obj.name, quantized))

    return total_limited, 0


def cull_unused_material_slots(armature):
    """Remove material slots from each child mesh that no polygon references.
    Returns the total number of slots stripped across all child meshes.
    """
    removed = 0
    for child in armature.children:
        if child.type != 'MESH' or child.data is None:
            continue
        used = {p.material_index for p in child.data.polygons}
        for idx in reversed(range(len(child.material_slots))):
            if idx in used:
                continue
            bpy.ops.object.select_all(action='DESELECT')
            child.select_set(True)
            bpy.context.view_layer.objects.active = child
            child.active_material_index = idx
            bpy.ops.object.material_slot_remove()
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# Textures
# ---------------------------------------------------------------------------

MAX_TEXTURE_DIM = 512


def prepare_texture_sizes(armature):
    """Downscale any texture larger than MAX_TEXTURE_DIM on either axis.

    Scales proportionally so the larger dimension becomes MAX_TEXTURE_DIM.
    UVs are in normalized [0, 1] space in Blender, so no UV remap is needed.

    Returns the number of images that were rescaled.
    """
    images_seen = set()
    count = 0

    for child in armature.children:
        if child.type != 'MESH':
            continue
        for slot in child.material_slots:
            if not slot.material or not slot.material.use_nodes:
                continue
            for node in slot.material.node_tree.nodes:
                if node.bl_idname != 'ShaderNodeTexImage' or not node.image:
                    continue
                img = node.image
                if img.name in images_seen:
                    continue
                images_seen.add(img.name)

                w, h = img.size[0], img.size[1]
                if w <= MAX_TEXTURE_DIM and h <= MAX_TEXTURE_DIM:
                    continue
                if w == 0 or h == 0:
                    continue

                ratio = min(MAX_TEXTURE_DIM / w, MAX_TEXTURE_DIM / h)
                new_w = max(1, int(w * ratio))
                new_h = max(1, int(h * ratio))
                img.scale(new_w, new_h)
                count += 1
                print("    %s: %dx%d -> %dx%d" %
                      (img.name, w, h, new_w, new_h))

    return count


def _analyze_texture(img):
    """Analyze an image's pixels and return a suitable GX format name.
    Returns a format string like 'CMPR', 'I8', etc.
    """
    w, h = img.size[0], img.size[1]
    if w == 0 or h == 0:
        return None

    pixels = img.pixels[:]
    num_pixels = w * h

    is_gray = True
    has_alpha = False
    unique_colors = set()
    max_unique = 260

    for i in range(num_pixels):
        base = i * 4
        r, g, b, a = pixels[base], pixels[base+1], pixels[base+2], pixels[base+3]

        if a < 0.998:
            has_alpha = True

        if is_gray and (abs(r - g) > 0.004 or abs(r - b) > 0.004):
            is_gray = False

        if len(unique_colors) < max_unique:
            ri = min(255, int(r * 255 + 0.5))
            gi = min(255, int(g * 255 + 0.5))
            bi = min(255, int(b * 255 + 0.5))
            ai = min(255, int(a * 255 + 0.5))
            unique_colors.add((ri, gi, bi, ai))

    n_colors = len(unique_colors)

    if is_gray:
        if has_alpha:
            return 'IA8'
        else:
            return 'I8'
    elif n_colors <= 16:
        return 'C4'
    elif n_colors <= 256:
        return 'C8'
    elif has_alpha:
        return 'RGB5A3'
    else:
        return 'CMPR'


def prepare_texture_formats(armature):
    """Auto-select GX texture formats for textures still on 'AUTO'.
    Returns the number of textures that were assigned a format.
    """
    images_seen = set()
    count = 0

    for child in armature.children:
        if child.type != 'MESH':
            continue
        for slot in child.material_slots:
            if not slot.material or not slot.material.use_nodes:
                continue
            for node in slot.material.node_tree.nodes:
                if node.bl_idname == 'ShaderNodeTexImage' and node.image:
                    img = node.image
                    if img.name in images_seen:
                        continue
                    images_seen.add(img.name)

                    if img.dat_gx_format != 'AUTO':
                        continue

                    fmt = _analyze_texture(img)
                    if fmt:
                        img.dat_gx_format = fmt
                        count += 1
                        print("    %s (%dx%d): %s" % (img.name, img.size[0], img.size[1], fmt))

    return count


_GX_FORMAT_ITEMS = [
    ('AUTO', 'AUTO (Pick based on content)', 'Let the exporter choose a format'),
    ('CMPR', 'CMPR (Compressed)', 'S3TC/DXT1 compressed — best for most textures'),
    ('RGBA8', 'RGBA8 (Full Quality)', '32-bit full quality RGBA'),
    ('RGB565', 'RGB565 (No Alpha)', '16-bit RGB, no alpha'),
    ('RGB5A3', 'RGB5A3 (RGB+Alpha)', '16-bit with optional alpha'),
    ('I4', 'I4 (Grayscale 4-bit)', '4-bit grayscale'),
    ('I8', 'I8 (Grayscale 8-bit)', '8-bit grayscale (intensity = alpha)'),
    ('IA4', 'IA4 (Intensity+Alpha 4-bit)', '4-bit intensity + 4-bit alpha'),
    ('IA8', 'IA8 (Intensity+Alpha 8-bit)', '8-bit intensity + 8-bit alpha'),
    ('C4', 'C4 (4-bit Palette)', 'Palette indexed, up to 16 colors'),
    ('C8', 'C8 (8-bit Palette)', 'Palette indexed, up to 256 colors'),
]


def _register_image_props():
    """Register `dat_gx_format` on bpy.types.Image if not already registered.
    Mirrors the addon's definition in BlenderPlugin.py so the prep script
    works even when the addon is disabled or its register() hasn't run in
    the current session (e.g. after a botched script reload).
    """
    if hasattr(bpy.types.Image, 'dat_gx_format'):
        return
    from bpy.props import EnumProperty
    bpy.types.Image.dat_gx_format = EnumProperty(
        name="GX Texture Format",
        description="GX texture format used when exporting this texture. Auto selects based on pixel content.",
        items=_GX_FORMAT_ITEMS,
        default='AUTO',
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__" or True:
    print("=== Prepare for bare .dat Export ===")

    _register_image_props()

    baked = bake_transforms()
    if baked:
        print("  Baked transforms on %d object(s) [direct data mutation]" % baked)
        for arm in (o for o in bpy.data.objects if o.type == 'ARMATURE'):
            child = next((o for o in bpy.data.objects
                          if o.parent is arm and o.type == 'MESH' and o.data and o.data.vertices),
                         None)
            if child is None:
                continue
            longest = max((b.length for b in arm.data.bones), default=0.0)
            v = max((v.co.length for v in child.data.vertices), default=0.0)
            print("    %s: longest bone = %.3f, max mesh vertex = %.3f"
                  % (arm.name, longest, v))

    normalize_camera_aspect()

    armatures = [obj for obj in bpy.data.objects if obj.type == 'ARMATURE']
    if not armatures:
        print("  No armatures in scene (weight / texture steps skipped)")

    for arm in armatures:
        limited, _ = prepare_mesh_weights(arm)
        if limited:
            print("  Limited %d vertex weights on '%s'" % (limited, arm.name))

        culled = cull_unused_material_slots(arm)
        if culled:
            print("  Culled %d unused material slot(s) on '%s'" % (culled, arm.name))

        size_count = prepare_texture_sizes(arm)
        if size_count:
            print("  Downscaled %d texture(s) on '%s'" % (size_count, arm.name))

        fmt_count = prepare_texture_formats(arm)
        if fmt_count:
            print("  Set GX format on %d texture(s) on '%s'" % (fmt_count, arm.name))

    print("=== Done ===")
