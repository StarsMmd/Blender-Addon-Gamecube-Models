"""Regression: sparsify must emit ≥2 keyframes for constant-value channels.

The game's per-FObj animation player (HSD_FObjInterpretAnim) treats
channels with a single keyframe as "no animation" and silently falls
back to the bone's rest-pose value for that channel. When an original
game-native animation holds a channel constant (e.g. achamo's Origin
bone rotation held at 0 across the idle), the orig PKX stores TWO
keyframes (start + end, same value) so the animation player engages
and overrides the rest pose.

Before this fix, both `_sparsify` and `_sparsify_bezier` collapsed
constant-value channels to a single keyframe. The game then reverted
each bone to its rest rotation, producing a visible "rotated at rest"
symptom (e.g. achamo's Origin has rest rotation -0.87 rad but every
animation's frame-0 rotation is 0; with single-keyframe collapse the
bone was stuck at -0.87 and the model appeared rotated ~50°).

Both sparsifiers must now emit 2 CONSTANT keyframes (start + end) for
constant-value channels, and 1 keyframe only when the source had a
single sample.
"""
from exporter.phases.describe.helpers.animations_decode import (
    _sparsify, _sparsify_bezier, _compute_slopes,
)
from shared.IR.enums import Interpolation


# --- _sparsify (linear path) ----------------------------------------------

def test_sparsify_constant_channel_emits_two_keyframes():
    fv = [(i, 0.0) for i in range(79)]
    result = _sparsify(fv)
    assert len(result) == 2, (
        "constant-value channel must emit 2 keyframes so the game's "
        "animation player engages (single-keyframe channels fall back "
        "to rest pose, producing visible 'stuck at rest' bugs)"
    )
    assert result[0].interpolation == Interpolation.CONSTANT
    assert result[1].interpolation == Interpolation.CONSTANT
    assert result[0].value == 0.0
    assert result[1].value == 0.0
    assert result[0].frame == 0
    assert result[1].frame == 78


def test_sparsify_constant_non_zero_value_emits_two_keyframes():
    fv = [(i, 3.14159) for i in range(60)]
    result = _sparsify(fv)
    assert len(result) == 2
    assert abs(result[0].value - 3.14159) < 1e-9
    assert abs(result[1].value - 3.14159) < 1e-9


def test_sparsify_single_sample_emits_one_keyframe():
    """A channel with just one sampled frame has no range to span —
    emit a single CONSTANT keyframe, not two copies."""
    result = _sparsify([(5, 2.5)])
    assert len(result) == 1
    assert result[0].frame == 5
    assert result[0].value == 2.5


def test_sparsify_all_same_frame_no_expansion():
    """Degenerate input where every sample shares the same frame
    number — emit one keyframe (start==end, can't span a range)."""
    fv = [(7, 1.0), (7, 1.0), (7, 1.0)]
    result = _sparsify(fv)
    assert len(result) == 1
    assert result[0].frame == 7


def test_sparsify_linear_ramp_still_two_keyframes():
    """Non-constant channels shouldn't regress — linear ramp still
    collapses to two LINEAR endpoints."""
    fv = [(i, 2.0 * i) for i in range(10)]
    result = _sparsify(fv)
    assert len(result) == 2
    assert result[0].interpolation == Interpolation.LINEAR


# --- _sparsify_bezier (bezier path) ---------------------------------------

def test_sparsify_bezier_constant_channel_emits_two_keyframes():
    fv = [(i, -0.87) for i in range(79)]
    slopes = _compute_slopes(fv)
    result = _sparsify_bezier(fv, slopes)
    assert len(result) == 2, (
        "bezier sparsifier must also emit 2 keyframes for constant "
        "channels — same rest-pose-fallback bug applies"
    )
    assert result[0].interpolation == Interpolation.CONSTANT
    assert result[1].interpolation == Interpolation.CONSTANT
    assert abs(result[0].value - (-0.87)) < 1e-9
    assert abs(result[1].value - (-0.87)) < 1e-9
    assert result[0].frame == 0
    assert result[1].frame == 78


def test_sparsify_bezier_single_sample_emits_one_keyframe():
    result = _sparsify_bezier([(0, 5.0)], [0.0])
    assert len(result) == 1
    assert result[0].interpolation == Interpolation.CONSTANT


def test_sparsify_bezier_constant_start_end_frames_match_input():
    """Start frame should match fv[0][0], end frame should match fv[-1][0]."""
    fv = [(10 + i, 7.0) for i in range(30)]  # frames 10..39
    slopes = _compute_slopes(fv)
    result = _sparsify_bezier(fv, slopes)
    assert len(result) == 2
    assert result[0].frame == 10
    assert result[1].frame == 39


# --- Context / invariant ---------------------------------------------------

def test_achamo_scenario_constant_rotation_preserves_override():
    """Replicates the achamo Origin-bone scenario: rest rotation is
    -0.87 but every animation-frame rotation is 0. The sparsified
    output must contain 2 keyframes at value 0 so the game plays the
    override and doesn't fall back to rest.
    """
    # Simulate a 79-frame animation where every sample is 0.0 (the
    # importer evaluated the fcurve at each frame and got the same
    # value because the source held the channel constant).
    fv = [(i, 0.0) for i in range(79)]
    result_linear = _sparsify(fv)
    result_bezier = _sparsify_bezier(fv, _compute_slopes(fv))

    for result, path in [(result_linear, 'linear'), (result_bezier, 'bezier')]:
        assert len(result) == 2, (
            f"{path} sparsifier emitted {len(result)} keyframes for a "
            "held-at-zero channel; game will revert to rest pose with only 1 kf"
        )
        assert all(kf.value == 0.0 for kf in result)
        assert result[-1].frame > result[0].frame, (
            f"{path}: the two keyframes must span the animation range, "
            "not sit at the same frame"
        )
