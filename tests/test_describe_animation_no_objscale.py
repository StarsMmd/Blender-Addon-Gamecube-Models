"""Regression: animation fcurves must NOT be scaled by armature.obj_scale.

Earlier, `describe_bone_animations` multiplied every location fcurve by
`(sx+sy+sz)/3` — a uniform-average obj-scale factor that compensated for
the skeleton applying scale component-wise to bone rest positions.

Once the skeleton bakes the full `obj_transform` uniformly via matrix
multiplication, the rest matrices already contain the armature's rotation
AND scale correctly. Blender stores pose-bone fcurves
in bone-local space — unaffected by the armature's object transform — so
unbaking them against the new rest matrices should pass them through
UNSCALED. The old uniform-average workaround would have silently damaged
non-uniform-scale armatures.

This test pins down the invariant: a pose-location fcurve keyframe at
value V produces an IR location-track value that depends only on rest
pose geometry, NOT on `armature.matrix_world.to_scale()`.
"""
import pytest

pytest.importorskip("mathutils")

from mathutils import Matrix

from exporter.phases.describe.helpers.animations_decode import (
    _unbake_bone_track, _build_bone_data,
)
from shared.IR.skeleton import IRBone
from shared.IR.enums import ScaleInheritance


def _identity_matrix():
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _make_rest_bone():
    """Bone at origin with identity rotation/scale — unbake at this rest
    returns the raw Blender pose values, so any stray obj-scale factor
    would show up plainly in the output."""
    return IRBone(
        name='bone',
        parent_index=None,
        position=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        inverse_bind_matrix=_identity_matrix(),
        flags=0,
        is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED,
        ik_shrink=False,
        world_matrix=_identity_matrix(),
        local_matrix=_identity_matrix(),
        normalized_world_matrix=_identity_matrix(),
        normalized_local_matrix=_identity_matrix(),
        scale_correction=_identity_matrix(),
        accumulated_scale=(1.0, 1.0, 1.0),
    )


class _ConstantFCurve:
    """Tiny fcurve stand-in: one keyframe, evaluate() returns the value."""
    def __init__(self, value):
        self.value = value

    def evaluate(self, frame):
        return self.value


class _NoOpLogger:
    def info(self, *a, **k): pass
    def debug(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def error(self, *a, **k): pass


def test_location_fcurve_passes_through_unscaled():
    """A location.x fcurve of 2.5 on an identity rest must unbake to 2.5.

    If any obj-scale factor were re-introduced, this would drift.
    """
    bones = [_make_rest_bone()]
    bone_data = _build_bone_data(bones)
    channels = {'location': {0: _ConstantFCurve(2.5)}}
    track = _unbake_bone_track(
        'bone', 0, channels, bone_data, bones,
        frame_start=0, frame_end=0, end_frame=1,
        logger=_NoOpLogger(),
        use_bezier=False,
    )
    # First and only keyframe of location.x
    assert track.location[0][0].value == pytest.approx(2.5, abs=1e-6)
    # Y and Z channels untouched
    assert track.location[1][0].value == pytest.approx(0.0, abs=1e-6)
    assert track.location[2][0].value == pytest.approx(0.0, abs=1e-6)


def test_unbake_signature_drops_loc_scale():
    """The `loc_scale` parameter has been removed; kwargs must not leak it."""
    import inspect

    sig_action = inspect.signature(
        __import__(
            'exporter.phases.describe.helpers.animations_decode',
            fromlist=['_describe_action'],
        )._describe_action
    )
    sig_unbake = inspect.signature(_unbake_bone_track)

    assert 'loc_scale' not in sig_action.parameters, \
        "_describe_action must not carry loc_scale any more"
    assert 'loc_scale' not in sig_unbake.parameters, \
        "_unbake_bone_track must not carry loc_scale any more"


def test_location_independent_of_hypothetical_obj_scale_kwarg():
    """Defensive: if somebody re-introduces a loc_scale multiplier, this
    test is the canary. Two identical inputs must produce the same output
    — there is nothing the caller can pass to distort the location."""
    bones = [_make_rest_bone()]
    bone_data = _build_bone_data(bones)
    channels = {'location': {0: _ConstantFCurve(3.0), 1: _ConstantFCurve(-1.5)}}
    t1 = _unbake_bone_track('bone', 0, channels, bone_data, bones,
                            0, 0, 1, _NoOpLogger(), use_bezier=False)
    t2 = _unbake_bone_track('bone', 0, channels, bone_data, bones,
                            0, 0, 1, _NoOpLogger(), use_bezier=False)
    assert t1.location[0][0].value == t2.location[0][0].value == pytest.approx(3.0)
    assert t1.location[1][0].value == t2.location[1][0].value == pytest.approx(-1.5)
