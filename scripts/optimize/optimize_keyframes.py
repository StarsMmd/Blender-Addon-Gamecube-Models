"""Standalone Blender script: thin out keyframes on every action.

Run from Blender's Scripting panel (Text Editor > Run Script). Two-pass
reduction on every F-curve in every action:

  1. Error-decimate: remove keyframes whose value is within ERROR_TOLERANCE
     (relative to the curve's value range) of the linear interpolation
     between their neighbours. Iterates until no more keys are removable.
  2. Thin: keep every Nth interior keyframe (first and last always kept).
     N = KEEP_EVERY_NTH_KEYFRAME. Set to 1 to disable, 2 to halve, 3 to keep
     a third, etc.

The first pass is content-aware (drops only redundant keys); the second is
a flat 1/N reduction on top. Both endpoints are always preserved.

This script is fully standalone — no imports from the plugin codebase.
"""
import bpy


ERROR_TOLERANCE = 0.05
KEEP_EVERY_NTH_KEYFRAME = 2


def _curve_value_range(fcurve):
    if len(fcurve.keyframe_points) < 2:
        return 1.0
    vals = [k.co.y for k in fcurve.keyframe_points]
    span = max(vals) - min(vals)
    return span if span > 1e-9 else 1.0


def _error_decimate(fcurve, tolerance):
    """Iteratively drop interior keys whose value is within `tolerance` of
    the linear interp of their immediate neighbours. `tolerance` is a
    fraction of the curve's value range."""
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
                i += 2  # skip the next one so neighbours stay intact this pass
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
    """Keep every Nth interior keyframe; first and last always kept."""
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


def optimize_keyframes(tolerance=ERROR_TOLERANCE, keep_every_n=KEEP_EVERY_NTH_KEYFRAME):
    actions = list(bpy.data.actions)
    if not actions:
        print("[optimize_keyframes] no actions in scene.")
        return

    total_before = 0
    total_after = 0
    for action in actions:
        before = sum(len(fc.keyframe_points) for fc in action.fcurves)
        decimated = 0
        thinned = 0
        for fc in action.fcurves:
            decimated += _error_decimate(fc, tolerance)
            thinned += _thin_keyframes(fc, keep_every_n)
        after = sum(len(fc.keyframe_points) for fc in action.fcurves)
        total_before += before
        total_after += after
        print("  %s: %d → %d keys (decimate -%d, thin -%d)"
              % (action.name, before, after, decimated, thinned))

    print("[optimize_keyframes] done: %d → %d keys across %d actions"
          % (total_before, total_after, len(actions)))


if __name__ == '__main__':
    optimize_keyframes()
