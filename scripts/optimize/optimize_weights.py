"""Standalone Blender script: cap bone weights per vertex on rigged meshes.

Run from Blender's Scripting panel (Text Editor > Run Script). Iterates
every mesh parented to an armature and applies Blender's
`vertex_group_limit_total` op so each vertex retains at most
MAX_WEIGHTS_PER_VERTEX bone influences (lowest-weighted are dropped, the
remaining weights are re-normalised).

GameCube hardware caps at 4 weights per vertex; 3 is the practical default
matching `prepare_for_export.py` for size/quality balance.

This script is fully standalone — no imports from the plugin codebase.
"""
import bpy


MAX_WEIGHTS_PER_VERTEX = 3


def optimize_weights(limit=MAX_WEIGHTS_PER_VERTEX):
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    armatures = [o for o in bpy.context.view_layer.objects if o.type == 'ARMATURE']
    total_meshes = 0
    total_affected = 0

    for arm in armatures:
        bone_names = {b.name for b in arm.data.bones}
        meshes = [o for o in bpy.context.view_layer.objects
                  if o.type == 'MESH' and o.parent is arm]

        for mesh_obj in meshes:
            affected = 0
            for v in mesh_obj.data.vertices:
                bone_groups = [g for g in v.groups
                               if g.group < len(mesh_obj.vertex_groups)
                               and mesh_obj.vertex_groups[g.group].name in bone_names
                               and g.weight > 0.0]
                if len(bone_groups) > limit:
                    affected += 1

            if affected == 0:
                continue

            bpy.ops.object.select_all(action='DESELECT')
            mesh_obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_obj
            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
            bpy.ops.object.vertex_group_limit_total(limit=limit)
            bpy.ops.object.mode_set(mode='OBJECT')
            print("  %s: limited %d vertices to %d weights"
                  % (mesh_obj.name, affected, limit))
            total_meshes += 1
            total_affected += affected

    print("[optimize_weights] done: %d vertices clamped across %d meshes (limit %d)"
          % (total_affected, total_meshes, limit))


if __name__ == '__main__':
    optimize_weights()
