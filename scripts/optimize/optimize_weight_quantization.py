"""Standalone Blender script: quantise bone weights to fixed steps.

Run from Blender's Scripting panel (Text Editor > Run Script). Matches game
models which store per-vertex weights at 10% precision (1 / QUANT_STEPS).

For each mesh parented to an armature:
  1. Normalise weights so each vertex's bone weights sum to 1.0.
  2. Round every bone weight to the nearest 1/QUANT_STEPS.
  3. Normalise again (rounding breaks the sum-to-1 invariant).
  4. Round once more (the second normalise can drift off the grid).

Running this after `optimize_weights.py` (which caps weights per vertex) is
the intended order — fewer influences means less rounding error surfaces at
each step.

This script is fully standalone — no imports from the plugin codebase.
"""
import bpy


QUANT_STEPS = 10


def _round_to_step(value, steps):
    return round(value * steps) / steps


def optimize_weight_quantization(steps=QUANT_STEPS):
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    armatures = [o for o in bpy.context.view_layer.objects if o.type == 'ARMATURE']
    total_quantized = 0
    total_meshes = 0

    for arm in armatures:
        bone_names = {b.name for b in arm.data.bones}
        meshes = [o for o in bpy.context.view_layer.objects
                  if o.type == 'MESH' and o.parent is arm]

        for mesh_obj in meshes:
            bpy.ops.object.select_all(action='DESELECT')
            mesh_obj.select_set(True)
            bpy.context.view_layer.objects.active = mesh_obj
            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
            bpy.ops.object.vertex_group_normalize_all(lock_active=False)
            bpy.ops.object.mode_set(mode='OBJECT')

            quantized = 0
            for v in mesh_obj.data.vertices:
                for g in v.groups:
                    if g.group >= len(mesh_obj.vertex_groups):
                        continue
                    if mesh_obj.vertex_groups[g.group].name not in bone_names:
                        continue
                    q = _round_to_step(g.weight, steps)
                    if abs(q - g.weight) > 1e-4:
                        g.weight = q
                        quantized += 1

            if quantized == 0:
                continue

            bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
            bpy.ops.object.vertex_group_normalize_all(lock_active=False)
            bpy.ops.object.mode_set(mode='OBJECT')
            for v in mesh_obj.data.vertices:
                for g in v.groups:
                    if g.group < len(mesh_obj.vertex_groups):
                        if mesh_obj.vertex_groups[g.group].name in bone_names:
                            g.weight = _round_to_step(g.weight, steps)

            print("  %s: quantized %d weights to 1/%d steps"
                  % (mesh_obj.name, quantized, steps))
            total_quantized += quantized
            total_meshes += 1

    print("[optimize_weight_quantization] done: %d weights across %d meshes (1/%d step)"
          % (total_quantized, total_meshes, steps))


if __name__ == '__main__':
    optimize_weight_quantization()
