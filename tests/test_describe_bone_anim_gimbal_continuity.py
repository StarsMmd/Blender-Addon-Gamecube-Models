"""_unbake_* must pass prev_euler into Quaternion.to_euler for continuity.

Quaternion.to_euler('XYZ') has two valid decompositions near ‖Y‖ ≈ π/2
(gimbal lock): it can put the rotation into X or Z or split it. Without
a continuity hint, mathutils picks one deterministically but not
necessarily the one nearest the previous frame's Euler — adjacent
frames near gimbal can decompose to wildly different Euler triples for
nearly-identical orientations, producing an in-game flicker that our
Euler-unwrap pass doesn't catch (because the jump isn't exactly 2π on
any single axis; it's a branch switch across all three).

mathutils.Quaternion.to_euler(order, reference_euler) picks the branch
closest to `reference_euler`. _unbake_legacy and _unbake_direct must
accept and forward a `prev_euler` argument so _unbake_bone_track can
pass the previous frame's output as the reference.
"""
import inspect

from exporter.phases.describe.helpers import animations_decode as anim_helpers


def test_unbake_direct_accepts_prev_euler():
    sig = inspect.signature(anim_helpers._unbake_direct)
    assert 'prev_euler' in sig.parameters, (
        "_unbake_direct must accept a prev_euler kwarg so the caller can "
        "pass the previous frame's Euler into Quaternion.to_euler for "
        "gimbal-branch continuity."
    )


def test_unbake_legacy_accepts_prev_euler():
    sig = inspect.signature(anim_helpers._unbake_legacy)
    assert 'prev_euler' in sig.parameters, (
        "_unbake_legacy must accept a prev_euler kwarg (same reason as "
        "_unbake_direct)."
    )


def test_unbake_direct_passes_prev_euler_to_to_euler():
    src = inspect.getsource(anim_helpers._unbake_direct)
    assert "to_euler('XYZ', prev_euler)" in src, (
        "_unbake_direct must forward prev_euler into Quaternion.to_euler('XYZ', …) "
        "so gimbal-lock regions stay continuous across frames."
    )


def test_unbake_legacy_passes_prev_euler_to_to_euler():
    src = inspect.getsource(anim_helpers._unbake_legacy)
    assert "to_euler('XYZ', prev_euler)" in src, (
        "_unbake_legacy must forward prev_euler into Quaternion.to_euler('XYZ', …)."
    )


def test_unbake_bone_track_maintains_prev_euler_across_frames():
    src = inspect.getsource(anim_helpers._unbake_bone_track)
    # We assign prev_euler from the unbake result each iteration so the
    # next call sees it. Both must appear in the function body.
    assert "prev_euler = None" in src, (
        "_unbake_bone_track must initialise prev_euler = None before the "
        "frame sampling loop."
    )
    assert "prev_euler = Euler(r, 'XYZ')" in src, (
        "_unbake_bone_track must update prev_euler with each frame's "
        "computed Euler so the next frame's _unbake_* call receives it."
    )
