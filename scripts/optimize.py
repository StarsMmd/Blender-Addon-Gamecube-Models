"""Standalone Blender script: run every optimisation pass in one go.

Run from Blender's Scripting panel (Text Editor > Run Script). Duplicates
the core logic of the five individual optimize_*.py scripts (the project's
scripts policy bans cross-script imports) and runs them in this order:

  1. merge_verts           — weld coincident vertices (shrinks baseline tri count)
  2. polycount             — decimate to ≤ TARGET_TRIS
  3. weights               — cap bone weights per vertex
  4. weight_quantization   — quantise remaining weights to 1/QUANT_STEPS
  5. textures              — clamp images to ≤ MAX_TEX_DIM
  6. keyframes             — error-decimate + thin F-curve keys

Tune the constants at the top of this file — or run an individual script
for one-off passes.

This script is fully standalone — no imports from the plugin codebase.
"""
import bpy


TARGET_TRIS = 10000
MAX_WEIGHTS_PER_VERTEX = 3
QUANT_STEPS = 10
MAX_TEX_DIM = 256
MERGE_DISTANCE = 0.0001
KEYFRAME_ERROR_TOLERANCE = 0.05
KEEP_EVERY_NTH_KEYFRAME = 2


# ---------------------------------------------------------------------------
# Pass 1 — merge verts
# ---------------------------------------------------------------------------

def _run_merge_verts(distance):
    meshes = [o for o in bpy.context.view_layer.objects
              if o.type == 'MESH' and o.data is not None]
    before = sum(len(o.data.vertices) for o in meshes)
    for obj in meshes:
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=distance)
        bpy.ops.object.mode_set(mode='OBJECT')
    after = sum(len(o.data.vertices) for o in meshes)
    print("[1/6 merge_verts] %d → %d verts" % (before, after))


# ---------------------------------------------------------------------------
# Pass 2 — polycount
# ---------------------------------------------------------------------------

def _count_tris(mesh):
    return sum((len(p.vertices) - 2) for p in mesh.polygons)


def _run_polycount(target):
    meshes = [o for o in bpy.context.view_layer.objects
              if o.type == 'MESH' and o.data is not None]
    total = sum(_count_tris(o.data) for o in meshes)
    if total <= target:
        print("[2/6 polycount] %d tris ≤ target %d; skipped." % (total, target))
        return
    ratio = target / total
    for obj in meshes:
        if obj.data.shape_keys and len(obj.data.shape_keys.key_blocks) > 0:
            continue
        if _count_tris(obj.data) == 0:
            continue
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        mod = obj.modifiers.new(name='OptimizeDecimate', type='DECIMATE')
        mod.decimate_type = 'COLLAPSE'
        mod.ratio = ratio
        mod.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=mod.name)
    after = sum(_count_tris(o.data) for o in meshes)
    print("[2/6 polycount] %d → %d tris (ratio %.3f)" % (total, after, ratio))


# ---------------------------------------------------------------------------
# Pass 3 — weights
# ---------------------------------------------------------------------------

def _run_weights(limit):
    armatures = [o for o in bpy.context.view_layer.objects if o.type == 'ARMATURE']
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
            total_affected += affected
    print("[3/6 weights] %d vertices clamped to ≤ %d weights"
          % (total_affected, limit))


# ---------------------------------------------------------------------------
# Pass 4 — weight quantization
# ---------------------------------------------------------------------------

def _round_to_step(value, steps):
    return round(value * steps) / steps


def _run_weight_quantization(steps):
    armatures = [o for o in bpy.context.view_layer.objects if o.type == 'ARMATURE']
    total_quantized = 0
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
            total_quantized += quantized
    print("[4/6 weight_quantization] %d weights quantised to 1/%d steps"
          % (total_quantized, steps))


# ---------------------------------------------------------------------------
# Pass 5 — textures
# ---------------------------------------------------------------------------

def _largest_pow2_le(n):
    if n < 1:
        return 1
    p = 1
    while p * 2 <= n:
        p *= 2
    return p


def _run_textures(max_dim):
    images = [img for img in bpy.data.images
              if img.size[0] > 0 and img.size[1] > 0 and img.source != 'MOVIE']
    rescaled = 0
    for img in images:
        w, h = img.size[0], img.size[1]
        if w <= max_dim and h <= max_dim:
            continue
        longer = max(w, h)
        target_long = _largest_pow2_le(min(longer, max_dim))
        scale = target_long / longer
        new_w = max(_largest_pow2_le(int(w * scale)), 1)
        new_h = max(_largest_pow2_le(int(h * scale)), 1)
        if new_w == w and new_h == h:
            continue
        img.scale(new_w, new_h)
        rescaled += 1
    print("[5/6 textures] %d / %d images rescaled (cap %d)"
          % (rescaled, len(images), max_dim))


# ---------------------------------------------------------------------------
# Pass 6 — keyframes
# ---------------------------------------------------------------------------

def _curve_value_range(fcurve):
    if len(fcurve.keyframe_points) < 2:
        return 1.0
    vals = [k.co.y for k in fcurve.keyframe_points]
    span = max(vals) - min(vals)
    return span if span > 1e-9 else 1.0


def _error_decimate(fcurve, tolerance):
    span = _curve_value_range(fcurve)
    threshold = span * tolerance
    removed_total = 0
    while True:
        kps = fcurve.keyframe_points
        n = len(kps)
        if n < 3:
            break
        to_remove = []
        i = 1
        while i < n - 1:
            prev_co = kps[i - 1].co
            this_co = kps[i].co
            next_co = kps[i + 1].co
            dt = next_co.x - prev_co.x
            if dt <= 0:
                i += 1
                continue
            t = (this_co.x - prev_co.x) / dt
            interp = prev_co.y + t * (next_co.y - prev_co.y)
            if abs(this_co.y - interp) <= threshold:
                to_remove.append(i)
                i += 2
            else:
                i += 1
        if not to_remove:
            break
        for idx in reversed(to_remove):
            kps.remove(kps[idx], fast=True)
        removed_total += len(to_remove)
    fcurve.update()
    return removed_total


def _thin_keyframes(fcurve, keep_every_n):
    if keep_every_n <= 1:
        return 0
    kps = fcurve.keyframe_points
    n = len(kps)
    if n < 3:
        return 0
    to_remove = [i for i in range(1, n - 1) if (i % keep_every_n) != 0]
    for idx in reversed(to_remove):
        kps.remove(kps[idx], fast=True)
    fcurve.update()
    return len(to_remove)


def _run_keyframes(tolerance, keep_every_n):
    total_before = 0
    total_after = 0
    for action in bpy.data.actions:
        before = sum(len(fc.keyframe_points) for fc in action.fcurves)
        for fc in action.fcurves:
            _error_decimate(fc, tolerance)
            _thin_keyframes(fc, keep_every_n)
        after = sum(len(fc.keyframe_points) for fc in action.fcurves)
        total_before += before
        total_after += after
    print("[6/6 keyframes] %d → %d keys across %d actions"
          % (total_before, total_after, len(bpy.data.actions)))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def optimize():
    if bpy.context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    print("[optimize] begin")
    _run_merge_verts(MERGE_DISTANCE)
    _run_polycount(TARGET_TRIS)
    _run_weights(MAX_WEIGHTS_PER_VERTEX)
    _run_weight_quantization(QUANT_STEPS)
    _run_textures(MAX_TEX_DIM)
    _run_keyframes(KEYFRAME_ERROR_TOLERANCE, KEEP_EVERY_NTH_KEYFRAME)
    print("[optimize] done")


if __name__ == '__main__':
    optimize()
