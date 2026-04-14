"""Regression test: bone-animation export must not pick up other slots' frame spans.

sirnight ships a multi-slot Action where the armature's bone fcurves stop at
frame 51 but a MATERIAL slot carries UV-translation keyframes out to frame 90.
`action.frame_range` reports (0, 90), and before this fix the exporter used
that span to bake every bone — producing a PKX whose idle was ~90 frames with
everything past frame 51 flat-tailed.

`_bone_fcurves_frame_range` consults only the collected bone fcurves, so
material-side keyframes can no longer stretch the bone frame range.
"""
from exporter.phases.describe_blender.helpers.animations import (
    _bone_fcurves_frame_range,
)


class _FakeKP:
    def __init__(self, frame, value=0.0):
        self.co = (frame, value)


class _FakeFCurve:
    def __init__(self, keyframes):
        self.keyframe_points = [_FakeKP(f) for f in keyframes]


def _bone_fcurves(frames_per_bone):
    """{bone_name: {channel: {array_index: fcurve}}} with one location.x fcurve per bone."""
    return {
        name: {'location': {0: _FakeFCurve(frames)}}
        for name, frames in frames_per_bone.items()
    }


def test_frame_range_ignores_padding_not_in_bone_fcurves():
    # Bone fcurves span 0..51 only (sirnight idle shape).
    fcurves = _bone_fcurves({'Bone_002': list(range(0, 52))})
    assert _bone_fcurves_frame_range(fcurves) == (0, 51, 51)


def test_frame_range_uses_min_and_max_across_all_bones():
    fcurves = _bone_fcurves({
        'Bone_A': [5, 10, 15],
        'Bone_B': [0, 20],
        'Bone_C': [8, 12],
    })
    assert _bone_fcurves_frame_range(fcurves) == (0, 20, 20)


def test_frame_range_none_when_no_keyframes():
    fcurves = {'Bone_A': {'location': {0: _FakeFCurve([])}}}
    assert _bone_fcurves_frame_range(fcurves) is None


def test_frame_range_never_zero_for_single_keyframe():
    # A single keyframe at frame 7 must still produce end_frame >= 1, matching
    # the previous `max(1, end - start)` guarantee so downstream sampling
    # loops always execute at least once.
    fcurves = _bone_fcurves({'Bone_A': [7]})
    assert _bone_fcurves_frame_range(fcurves) == (7, 7, 1)


def test_frame_range_handles_fractional_frames():
    # Blender's NLA editor can place keyframes on non-integer frames.
    fcurves = _bone_fcurves({'Bone_A': [0.0, 12.5, 49.75]})
    assert _bone_fcurves_frame_range(fcurves) == (0, 49, 49)
