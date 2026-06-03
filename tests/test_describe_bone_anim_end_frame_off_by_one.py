"""Regression: _bone_fcurves_frame_range must return INCLUSIVE end_frame.

_unbake_bone_track iterates `range(frame_start, frame_end + 1)` — inclusive
on both ends — so the emitted AOBJ must declare `end_frame = frame_end - frame_start + 1`
(sample count). Without the +1, every animation round-trips as 1/30 s
shorter than the source PKX: the game's state machine compares against
the stored AOBJ end_frame to decide when to loop, so losing a frame per
animation compounds across sets and shifts every subsequent state.

Verified against 6 game-native PKXs (achamo, absol, rayquaza, cerebi,
deoxys, blacky): each AOBJ round-tripped exactly 1 frame shorter before
the fix and exactly matches the original after.
"""
from exporter.phases.describe.helpers.animations_decode import (
    _bone_fcurves_frame_range,
)


class _FakeKP:
    def __init__(self, frame):
        self.co = (frame, 0.0)


class _FakeFCurve:
    def __init__(self, frames):
        self.keyframe_points = [_FakeKP(f) for f in frames]


def _fcurves(frames):
    return {'B': {'location': {0: _FakeFCurve(frames)}}}


def test_end_frame_is_inclusive_sample_count():
    # Keyframes at 0..78 → 79 samples → end_frame = 79.
    assert _bone_fcurves_frame_range(_fcurves(range(0, 79))) == (0, 78, 79)


def test_end_frame_when_first_keyframe_nonzero():
    # Keyframes at 5..20 → 16 samples. Start/end preserved.
    assert _bone_fcurves_frame_range(_fcurves(range(5, 21))) == (5, 20, 16)


def test_end_frame_single_keyframe():
    # A lone keyframe at frame 7 → 1 sample → end_frame = 1.
    assert _bone_fcurves_frame_range(_fcurves([7])) == (7, 7, 1)
