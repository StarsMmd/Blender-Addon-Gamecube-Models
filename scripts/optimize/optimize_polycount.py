"""Standalone Blender script: decimate meshes down to a target triangle count.

Run from Blender's Scripting panel (Text Editor > Run Script). Operates on
every mesh in the scene. If the total triangle count is at or below
TARGET_TRIS, does nothing. Otherwise applies a DECIMATE modifier with a
ratio of TARGET_TRIS / current_total to every mesh, then applies the
modifier so the reduction is permanent.

Rigging-aware: preserves vertex groups and shape keys are skipped (decimate
cannot run on meshes with shape keys — those meshes are left untouched).

This script is fully standalone — no imports from the plugin codebase.
"""
import bpy


TARGET_TRIS = 10000


def _count_tris(mesh):
    return sum((len(p.vertices) - 2) for p in mesh.polygons)


def _apply_decimate(obj, ratio):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new(name='OptimizeDecimate', type='DECIMATE')
    mod.decimate_type = 'COLLAPSE'
    mod.ratio = ratio
    mod.use_collapse_triangulate = True
    bpy.ops.object.modifier_apply(modifier=mod.name)


def optimize_polycount(target_tris=TARGET_TRIS):
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    meshes = [o for o in bpy.context.view_layer.objects
              if o.type == 'MESH' and o.data is not None]
    total_before = sum(_count_tris(o.data) for o in meshes)

    if total_before <= target_tris:
        print("[optimize_polycount] %d tris ≤ target %d; skipping."
              % (total_before, target_tris))
        return

    ratio = target_tris / total_before
    print("[optimize_polycount] %d tris → target %d (ratio %.3f)"
          % (total_before, target_tris, ratio))

    for obj in meshes:
        if obj.data.shape_keys is not None and len(obj.data.shape_keys.key_blocks) > 0:
            print("  skip %s (has shape keys)" % obj.name)
            continue
        before = _count_tris(obj.data)
        if before == 0:
            continue
        _apply_decimate(obj, ratio)
        after = _count_tris(obj.data)
        print("  %s: %d → %d tris" % (obj.name, before, after))

    total_after = sum(_count_tris(o.data) for o in meshes)
    print("[optimize_polycount] done: %d → %d tris" % (total_before, total_after))


if __name__ == '__main__':
    optimize_polycount()
