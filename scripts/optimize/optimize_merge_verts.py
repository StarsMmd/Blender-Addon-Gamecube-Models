"""Standalone Blender script: merge coincident vertices on every mesh.

Run from Blender's Scripting panel (Text Editor > Run Script). Iterates
every mesh in the scene, enters edit mode, selects all, and runs
`mesh.remove_doubles` with MERGE_DISTANCE. Cleans up duplicate geometry
common in GLB / FBX rips where the source split verts on every UV / normal
seam.

UVs and normals at merged points are averaged, which can introduce minor
seam artefacts on complex shading. Skip this pass on assets where exact
shading boundaries matter.

This script is fully standalone — no imports from the plugin codebase.
"""
import bpy


MERGE_DISTANCE = 0.0001


def optimize_merge_verts(distance=MERGE_DISTANCE):
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    meshes = [o for o in bpy.context.view_layer.objects
              if o.type == 'MESH' and o.data is not None]
    total_before = 0
    total_after = 0

    for obj in meshes:
        before = len(obj.data.vertices)
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=distance)
        bpy.ops.object.mode_set(mode='OBJECT')
        after = len(obj.data.vertices)
        if after != before:
            print("  %s: %d → %d verts (-%d)" % (obj.name, before, after, before - after))
        total_before += before
        total_after += after

    print("[optimize_merge_verts] done: %d → %d verts across %d meshes"
          % (total_before, total_after, len(meshes)))


if __name__ == '__main__':
    optimize_merge_verts()
