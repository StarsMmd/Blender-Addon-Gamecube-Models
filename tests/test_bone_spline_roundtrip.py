"""JOBJ_SPLINE joint-property round-trip: describe → compose.

Map joints can carry a Spline as their `property` (a motion path / camera
rail). describe lifts it into IRBone.spline and compose re-emits the Spline
node, so the NIN round-trip stops counting it as a miss. Curve values are
carried verbatim in GC units for exact fidelity.
"""
from types import SimpleNamespace

from importer.phases.describe.helpers.bones import _describe_joint_spline
from exporter.phases.compose.helpers.bones import _compose_joint_spline
from shared.IR.skeleton import IRBone, IRBoneSpline
from shared.IR.enums import ScaleInheritance
from shared.Constants.hsd import JOBJ_SPLINE


def _make_spline(flags=0x300, n=3, f0=0.5, f1=40.0,
                 s1=None, s2=None, s3=None):
    return SimpleNamespace(flags=flags, n=n, f0=f0, f1=f1, s1=s1, s2=s2, s3=s3)


def _make_joint(flags, prop=None):
    return SimpleNamespace(flags=flags, property=prop)


def _bone_with_spline(spline):
    return IRBone(
        name="b", parent_index=None,
        position=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1),
        inverse_bind_matrix=None, flags=JOBJ_SPLINE, is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED, ik_shrink=False,
        world_matrix=None, local_matrix=None,
        normalized_world_matrix=None, normalized_local_matrix=None,
        scale_correction=None, accumulated_scale=(1, 1, 1),
        spline=spline,
    )


class TestDescribeJointSpline:

    def test_no_spline_flag_returns_none(self):
        j = _make_joint(flags=0, prop=_make_spline())
        assert _describe_joint_spline(j) is None

    def test_flag_but_no_property_returns_none(self):
        assert _describe_joint_spline(_make_joint(flags=JOBJ_SPLINE, prop=None)) is None

    def test_arrays_lifted(self):
        sp = _make_spline(
            s1=[[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
            s2=[0.0, 0.5, 1.0],
            s3=[[1.0, 2.0, 3.0, 4.0, 5.0]],
        )
        ir = _describe_joint_spline(_make_joint(flags=JOBJ_SPLINE, prop=sp))
        assert ir.flags == 0x300 and ir.n == 3 and ir.f0 == 0.5
        assert ir.control_points == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
        assert ir.knots == [0.0, 0.5, 1.0]
        assert ir.coefficients == [[1.0, 2.0, 3.0, 4.0, 5.0]]


class TestComposeJointSpline:

    def test_no_spline_returns_none(self):
        bone = _bone_with_spline(None)
        assert _compose_joint_spline(bone) is None

    def test_spline_emitted(self):
        ir = IRBoneSpline(flags=0x300, n=3, f0=0.5, f1=40.0,
                          control_points=[[1.0, 2.0, 3.0]],
                          knots=[0.0, 1.0],
                          coefficients=[[1.0, 2.0, 3.0, 4.0, 5.0]])
        node = _compose_joint_spline(_bone_with_spline(ir))
        assert node.flags == 0x300 and node.n == 3
        assert node.s1 == [[1.0, 2.0, 3.0]]
        assert node.s2 == [0.0, 1.0]
        assert node.s3 == [[1.0, 2.0, 3.0, 4.0, 5.0]]


class TestSplineRoundTrip:

    def test_describe_then_compose_preserves_values(self):
        sp = _make_spline(
            flags=0x300, n=3, f0=0.5, f1=39.6,
            s1=[[-14.6, 5.0, 32.0], [25.0, 5.0, 32.0]],
            s2=[0.0, 0.5, 1.0],
            s3=[[882.0, 0.0, -1764.0, 0.0, 882.0]],
        )
        ir = _describe_joint_spline(_make_joint(flags=JOBJ_SPLINE, prop=sp))
        node = _compose_joint_spline(_bone_with_spline(ir))
        assert node.flags == sp.flags and node.n == sp.n
        assert node.f0 == sp.f0 and node.f1 == sp.f1
        assert node.s1 == sp.s1
        assert node.s2 == sp.s2
        assert node.s3 == sp.s3


class TestSplineBRCurveMapping:
    """IR → BR (Blender Curve) → IR is a deliberately lossy native mapping.

    Control points and a representative curve type survive; the GX f0/f1 and
    the precomputed knots / coefficients do not (Blender recomputes curve
    interpolation from the points).
    """

    def test_control_points_and_type_map_through_curve(self):
        from importer.phases.plan.helpers.armature import _plan_bone_spline as to_br
        from exporter.phases.plan.helpers.armature import _plan_bone_spline as to_ir
        from shared.BR.armature import BRBoneSpline

        # GX type 3 (cardinal) lives in the flags high byte → NURBS.
        o = IRBoneSpline(flags=3 << 8, n=2, f0=0.5, f1=39.6,
                         control_points=[[-14.6, 5.0, 32.0], [25.0, 5.0, 32.0]],
                         knots=[0.0, 0.5, 1.0],
                         coefficients=[[882.0, 0.0, -1764.0, 0.0, 882.0]])
        br = to_br(o)
        assert isinstance(br, BRBoneSpline)
        assert br.curve_type == 'NURBS'
        assert br.control_points == [[-14.6, 5.0, 32.0], [25.0, 5.0, 32.0]]

        r = to_ir(br)
        assert r.control_points == o.control_points
        assert r.n == 2
        assert r.knots is None and r.coefficients is None  # dropped
        assert (r.flags >> 8) == 2  # NURBS resolves back to B-spline type

    def test_curve_type_mapping(self):
        from importer.phases.plan.helpers.armature import _plan_bone_spline as to_br
        for gx_type, expect in [(0, 'POLY'), (1, 'BEZIER'), (2, 'NURBS'), (3, 'NURBS')]:
            br = to_br(IRBoneSpline(flags=gx_type << 8, n=1, f0=0, f1=0,
                                    control_points=[[0, 0, 0]]))
            assert br.curve_type == expect

    def test_plan_legs_none_passthrough(self):
        from importer.phases.plan.helpers.armature import _plan_bone_spline as to_br
        from exporter.phases.plan.helpers.armature import _plan_bone_spline as to_ir
        assert to_br(None) is None
        assert to_ir(None) is None
