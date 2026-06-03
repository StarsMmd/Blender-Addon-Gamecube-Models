"""Tests for the responsibility-bounded helpers split out of _describe_bone_track."""
from types import SimpleNamespace

from importer.phases.describe.helpers.animations import (
    _compose_rest_local_matrix, _resolve_spline_node_data, _compose_spline_world_matrix,
)
from shared.helpers.math_shim import Matrix
from shared.helpers.scale import GC_TO_METERS
from shared.IR.animation import IRKeyframe
from shared.IR.enums import Interpolation


def _kf(value, frame=0):
    return IRKeyframe(frame=frame, value=value, interpolation=Interpolation.LINEAR)


def _joint(scale=(1.0, 1.0, 1.0), rotation=(0.0, 0.0, 0.0), position=(0.0, 0.0, 0.0)):
    return SimpleNamespace(scale=scale, rotation=rotation, position=position)


class TestComposeRestLocalMatrix:
    def test_identity_joint_yields_identity_matrix(self):
        m = _compose_rest_local_matrix(_joint(), [[], [], []])
        for r in range(4):
            for c in range(4):
                expected = 1.0 if r == c else 0.0
                assert abs(m[r][c] - expected) < 1e-6

    def test_translation_scaled_to_meters(self):
        # joint position is in GC units; rest matrix must convert to meters.
        m = _compose_rest_local_matrix(_joint(position=(100.0, 0.0, 0.0)), [[], [], []])
        assert abs(m[0][3] - 100.0 * GC_TO_METERS) < 1e-6

    def test_near_zero_rest_uses_visible_scale_from_channels(self):
        scale_channels = [
            [_kf(0.7, frame=0), _kf(0.7, frame=10)],
            [_kf(0.5, frame=0)],
            [_kf(0.3, frame=0)],
        ]
        m = _compose_rest_local_matrix(_joint(scale=(0.0, 0.0, 0.0)), scale_channels)
        assert abs(m[0][0] - 0.7) < 1e-6
        assert abs(m[1][1] - 0.5) < 1e-6
        assert abs(m[2][2] - 0.3) < 1e-6

    def test_near_zero_rest_falls_back_to_rest_when_no_visible(self):
        # No keyframes — best-visible scan returns None, rest_scale is used as-is.
        m = _compose_rest_local_matrix(_joint(scale=(0.0, 0.0, 0.0)), [[], [], []])
        assert abs(m[0][0]) < 1e-9
        assert abs(m[1][1]) < 1e-9


class TestResolveSplineNodeData:
    def test_returns_none_for_missing_joint(self):
        assert _resolve_spline_node_data(None) is None

    def test_returns_none_when_property_missing(self):
        joint = SimpleNamespace(property=None)
        assert _resolve_spline_node_data(joint) is None

    def test_returns_none_when_property_is_int(self):
        joint = SimpleNamespace(property=0x100)
        assert _resolve_spline_node_data(joint) is None

    def test_extracts_control_points_in_meters(self):
        spline = SimpleNamespace(s1=[[100.0, 200.0, 300.0]], flags=0x300, f0=0.5, n=1)
        joint = SimpleNamespace(property=spline)
        result = _resolve_spline_node_data(joint)
        assert result is not None
        cps, curve_type, tension, num_cvs = result
        assert abs(cps[0][0] - 100.0 * GC_TO_METERS) < 1e-6
        assert curve_type == 0x300 >> 8
        assert tension == 0.5
        assert num_cvs == 1


class TestComposeSplineWorldMatrix:
    def _bone(self, world=None, parent_index=None):
        b = SimpleNamespace(parent_index=parent_index)
        b.world_matrix = world or [list(row) for row in Matrix.Identity(4)]
        return b

    def test_returns_none_when_spline_joint_missing(self):
        bone = self._bone()
        assert _compose_spline_world_matrix(None, bone, [bone]) is None

    def test_uses_spline_local_when_no_parent(self):
        spline = SimpleNamespace(scale=(1.0, 1.0, 1.0), rotation=(0.0, 0.0, 0.0),
                                 position=(100.0, 0.0, 0.0))
        bone = self._bone(parent_index=None)
        m = _compose_spline_world_matrix(spline, bone, [bone])
        assert abs(m[0][3] - 100.0 * GC_TO_METERS) < 1e-6

    def test_anchors_under_parent_world(self):
        spline = SimpleNamespace(scale=(1.0, 1.0, 1.0), rotation=(0.0, 0.0, 0.0),
                                 position=(0.0, 0.0, 0.0))
        parent_world = [list(row) for row in Matrix.Identity(4)]
        parent_world[0][3] = 5.0  # parent translated +5x
        parent = SimpleNamespace(parent_index=None, world_matrix=parent_world)
        bone = self._bone(parent_index=0)
        m = _compose_spline_world_matrix(spline, bone, [parent, bone])
        # spline at origin under parent at x=5 → world x=5
        assert abs(m[0][3] - 5.0) < 1e-6
