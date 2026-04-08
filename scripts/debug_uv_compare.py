"""Diagnostic script: compare UV data between legacy and IR import pipelines.

Usage: Open in Blender's Scripting panel and run. Edit MODEL_PATH below.
Prints per-mesh UV comparison to the system console (Window > Toggle System Console).
"""
import bpy
import os

# ---- CONFIGURATION ----
MODEL_PATH = os.path.expanduser(
    "~/Documents/Projects/DAT plugin/end-to-end-test/Source/Assets/Models/battle_models/bangiras.pkx"
)
UV_DIFF_THRESHOLD = 0.001
MAX_DIFF_LINES = 20  # max diff lines to print per mesh
# -----------------------


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for mesh in bpy.data.meshes:
        bpy.data.meshes.remove(mesh)
    for mat in bpy.data.materials:
        bpy.data.materials.remove(mat)
    for img in bpy.data.images:
        bpy.data.images.remove(img)
    for action in bpy.data.actions:
        bpy.data.actions.remove(action)
    for armature in bpy.data.armatures:
        bpy.data.armatures.remove(armature)


def import_model(path, use_legacy):
    bpy.ops.import_model.dat(
        filepath=path,
        use_legacy=use_legacy,
        setup_workspace=False,
        import_lights=False,
        import_cameras=False,
        include_shiny=False,
        write_logs=False,
    )


def snapshot_meshes():
    """Capture all mesh data as plain Python dicts (survives scene clear)."""
    meshes = sorted(
        [obj for obj in bpy.data.objects if obj.type == 'MESH'],
        key=lambda o: o.name,
    )
    result = []
    for obj in meshes:
        md = obj.data
        # Capture polygon layout for face-level diff reporting
        poly_starts = []
        for poly in md.polygons:
            poly_starts.append(poly.loop_start)

        # Capture UV data
        uv = {}
        for uv_layer in md.uv_layers:
            uvs = [(d.uv[0], d.uv[1]) for d in uv_layer.data]
            uv[uv_layer.name] = uvs

        # Capture material info
        mat_names = [mat.name if mat else "None" for mat in md.materials]
        # Capture texture image names from material node trees
        tex_images = []
        for mat in md.materials:
            if mat and mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image:
                        tex_images.append(node.image.name)

        # Capture parent bone
        parent_bone = ""
        if obj.parent and obj.parent.type == 'ARMATURE':
            parent_bone = obj.parent.name
        # Capture vertex group names (bone weights)
        vgroups = [vg.name for vg in obj.vertex_groups]

        result.append({
            'name': obj.name,
            'verts': len(md.vertices),
            'faces': len(md.polygons),
            'loops': len(md.loops),
            'poly_starts': poly_starts,
            'uv': uv,
            'materials': mat_names,
            'textures': tex_images,
            'parent': parent_bone,
            'vgroups': vgroups,
        })
    return result


def compare_uv(ld, rd):
    """Compare UV data between two mesh snapshots. Returns True if match."""
    all_match = True

    if ld['faces'] != rd['faces']:
        print(f"  FACE COUNT MISMATCH: {ld['faces']} vs {rd['faces']}")
        all_match = False

    if ld['loops'] != rd['loops']:
        print(f"  LOOP COUNT MISMATCH: {ld['loops']} vs {rd['loops']}")
        all_match = False

    layers_a = set(ld['uv'].keys())
    layers_b = set(rd['uv'].keys())
    if layers_a != layers_b:
        print(f"  UV LAYER MISMATCH: {layers_a} vs {layers_b}")
        all_match = False

    for layer_name in sorted(layers_a & layers_b):
        uvs_a = ld['uv'][layer_name]
        uvs_b = rd['uv'][layer_name]
        if len(uvs_a) != len(uvs_b):
            print(f"  [{layer_name}] UV COUNT MISMATCH: {len(uvs_a)} vs {len(uvs_b)}")
            all_match = False
            continue

        diff_count = 0
        diff_lines = []
        # Use IR mesh poly_starts for face mapping (it's the one we want to fix)
        poly_starts = rd['poly_starts']
        for i, (a, b) in enumerate(zip(uvs_a, uvs_b)):
            du = abs(a[0] - b[0])
            dv = abs(a[1] - b[1])
            if du > UV_DIFF_THRESHOLD or dv > UV_DIFF_THRESHOLD:
                diff_count += 1
                if len(diff_lines) < MAX_DIFF_LINES:
                    # Find which face this loop belongs to
                    face_idx = "?"
                    vert_in_face = "?"
                    for fi in range(len(poly_starts)):
                        start = poly_starts[fi]
                        end = poly_starts[fi + 1] if fi + 1 < len(poly_starts) else rd['loops']
                        if start <= i < end:
                            face_idx = fi
                            vert_in_face = i - start
                            break
                    diff_lines.append(
                        f"    loop[{i}] face[{face_idx}].v{vert_in_face}: "
                        f"legacy=({a[0]:.4f}, {a[1]:.4f}) "
                        f"IR=({b[0]:.4f}, {b[1]:.4f}) "
                        f"delta=({du:.4f}, {dv:.4f})"
                    )

        if diff_count > 0:
            print(f"  [{layer_name}] {diff_count}/{len(uvs_a)} UVs differ:")
            for line in diff_lines:
                print(line)
            if diff_count > MAX_DIFF_LINES:
                print(f"    ... and {diff_count - MAX_DIFF_LINES} more")
            all_match = False

    return all_match


def main():
    if not os.path.exists(MODEL_PATH):
        print(f"ERROR: Model not found at {MODEL_PATH}")
        return

    out_path = "/tmp/uv_compare_output.txt"
    out_file = open(out_path, "w")

    def log(msg=""):
        print(msg)
        out_file.write(msg + "\n")

    log("=" * 70)
    log("MESH COMPARISON: Legacy vs IR pipeline")
    log(f"Model: {MODEL_PATH}")
    log("=" * 70)

    # --- Import via Legacy ---
    log("\n[1/2] Importing via LEGACY...")
    clear_scene()
    import_model(MODEL_PATH, use_legacy=True)
    legacy_data = snapshot_meshes()
    log(f"  Found {len(legacy_data)} meshes")
    for d in legacy_data:
        log(f"    {d['name']}: {d['verts']}v {d['faces']}f {d['loops']}l "
            f"uv={list(d['uv'].keys())} mat={d['materials']} tex={d['textures']}")

    # --- Import via IR ---
    log("\n[2/2] Importing via IR...")
    clear_scene()
    import_model(MODEL_PATH, use_legacy=False)
    ir_data = snapshot_meshes()
    log(f"  Found {len(ir_data)} meshes")
    for d in ir_data:
        log(f"    {d['name']}: {d['verts']}v {d['faces']}f {d['loops']}l "
            f"uv={list(d['uv'].keys())} mat={d['materials']} tex={d['textures']}")

    # --- Compare ---
    print("\n" + "=" * 70)
    print("COMPARISON")
    print("=" * 70)

    if len(legacy_data) != len(ir_data):
        log(f"\nMESH COUNT MISMATCH: legacy={len(legacy_data)}, IR={len(ir_data)}")

    # Match meshes by geometry signature (verts, faces, loops) since the
    # two pipelines produce meshes in different order (legacy creates
    # bound-box cubes first, IR creates textured meshes first).
    from collections import defaultdict
    legacy_by_sig = defaultdict(list)
    ir_by_sig = defaultdict(list)
    for d in legacy_data:
        sig = (d['verts'], d['faces'], d['loops'])
        legacy_by_sig[sig].append(d)
    for d in ir_data:
        sig = (d['verts'], d['faces'], d['loops'])
        ir_by_sig[sig].append(d)

    mismatched_uv = []
    mismatched_mat = []
    matched = []
    pair_idx = 0

    all_sigs = sorted(set(list(legacy_by_sig.keys()) + list(ir_by_sig.keys())))
    for sig in all_sigs:
        leg_list = legacy_by_sig.get(sig, [])
        ir_list = ir_by_sig.get(sig, [])
        count = min(len(leg_list), len(ir_list))
        if len(leg_list) != len(ir_list):
            log(f"\n  Signature {sig}: legacy has {len(leg_list)}, IR has {len(ir_list)}")
        for j in range(count):
            ld = leg_list[j]
            rd = ir_list[j]
            log(f"\n--- Pair {pair_idx}: legacy='{ld['name']}' vs IR='{rd['name']}' (sig={sig}) ---")

            # Material/texture comparison
            if ld['textures'] != rd['textures']:
                log(f"  TEXTURE MISMATCH: legacy={ld['textures']} vs IR={rd['textures']} <<<")
                mismatched_mat.append(pair_idx)
            elif ld['materials'] != rd['materials']:
                log(f"  Materials: legacy={ld['materials']} vs IR={rd['materials']}")
            else:
                log(f"  Materials: match ({ld['materials']})")

            if compare_uv(ld, rd):
                log("  UVs: MATCH")
                matched.append(pair_idx)
            else:
                log("  UVs: MISMATCH <<<")
                mismatched_uv.append(pair_idx)
            pair_idx += 1

    log("\n" + "=" * 70)
    log(f"SUMMARY: {len(matched)} UV match, {len(mismatched_uv)} UV mismatch, "
        f"{len(mismatched_mat)} texture mismatch out of {pair_idx} pairs")
    if mismatched_uv:
        log(f"UV mismatched pairs: {mismatched_uv}")
    if mismatched_mat:
        log(f"Texture mismatched pairs: {mismatched_mat}")
    log("=" * 70)

    out_file.close()
    print(f"\nOutput written to {out_path}")


main()
