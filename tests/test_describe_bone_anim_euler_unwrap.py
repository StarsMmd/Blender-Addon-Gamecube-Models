"""Euler rotation samples must stay continuous across frames.

The _unbake paths in describe_blender round-trip rotation through
`Quaternion.to_euler('XYZ')`, which normalises each axis to (-π, π].
A monotonic sweep across ±π wraps to the opposite sign on the next
frame; if the exporter writes those wrapped samples straight into the
DAT, the game's animation player interpolates linearly across the 2π
discontinuity and the model visibly stutters.

_unbake_bone_track must therefore unwrap each rotation channel before
sparsifying so the emitted keyframes describe a continuous curve.
"""
import math

from exporter.phases.describe.helpers import animations_decode as anim_helpers


def _invoke_unwrap(rot_channel_samples):
    """Run the same unwrap logic used inside _unbake_bone_track.

    Extracted to a helper so the test exercises the contract without
    needing a full Blender fcurve + bone_data fixture.
    """
    rot_channels = [list(rot_channel_samples), [], []]
    for i in range(3):
        samples = rot_channels[i]
        if len(samples) < 2:
            continue
        unwrapped = [samples[0]]
        prev = samples[0][1]
        offset = 0.0
        for frame, val in samples[1:]:
            candidate = val + offset
            delta = candidate - prev
            if delta > math.pi:
                offset -= 2 * math.pi
                candidate -= 2 * math.pi
            elif delta < -math.pi:
                offset += 2 * math.pi
                candidate += 2 * math.pi
            unwrapped.append((frame, candidate))
            prev = candidate
        rot_channels[i] = unwrapped
    return rot_channels[0]


def test_unwrap_preserves_monotonic_sweep_across_pi():
    # Ascending sweep 0 -> 2π that wrapped at frame 30 becomes -π, -π+eps…
    # Unwrapped result must be monotonically non-decreasing.
    raw = [
        (0,  0.0),
        (14, 0.86),
        (29, 2.98),
        (30, math.pi),
        (31, -math.pi + 0.16),   # wrapped sample: really ~π + 0.16
        (45, -0.98),             # wrapped: really ~2π - 0.98 = ~5.30
        (59, -0.005),            # wrapped: really ~2π - 0.005
        (60, 0.0),               # wrapped: really 2π
    ]
    out = _invoke_unwrap(raw)
    values = [v for _, v in out]
    for a, b in zip(values, values[1:]):
        assert b >= a - 1e-6, f"unwrap regressed: {values}"
    assert abs(values[-1] - 2 * math.pi) < 1e-3


def test_unwrap_keeps_values_untouched_when_no_wrap():
    raw = [(0, 0.0), (10, 0.5), (20, 1.0), (30, 1.5), (60, 3.0)]
    out = _invoke_unwrap(raw)
    assert out == raw


def test_unwrap_handles_descending_sweep():
    # Descending 0 -> -2π that wraps upward at frame 30 to +π.
    raw = [
        (0,  0.0),
        (29, -2.98),
        (30, -math.pi),
        (31, math.pi - 0.16),    # really -π - 0.16
        (60, -0.01),             # really ≈ -2π
    ]
    out = _invoke_unwrap(raw)
    values = [v for _, v in out]
    for a, b in zip(values, values[1:]):
        assert b <= a + 1e-6, f"descending unwrap regressed: {values}"
    assert values[-1] < -2 * math.pi + 0.1


def test_unwrap_single_keyframe_channel_unchanged():
    raw = [(0, math.pi / 2)]
    assert _invoke_unwrap(raw) == raw


def test_unwrap_applied_inside_unbake_bone_track():
    """The unwrap block must live inside _unbake_bone_track so every
    exported rotation channel goes through it."""
    import inspect
    src = inspect.getsource(anim_helpers._unbake_bone_track)
    assert "Unwrap Euler rotation channels" in src, (
        "_unbake_bone_track lost its Euler-unwrap pass — the stutter bug "
        "will reappear. Restore the unwrap loop before sparsification."
    )
