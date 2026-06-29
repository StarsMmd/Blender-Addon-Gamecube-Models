"""Regression: the IK pole-flip bit must survive export.

The GX runtime decides which way an IK middle joint (knee/elbow) folds purely
from the pole_flip bit (flag 0x4) on the first IK-hint reference of that joint —
it negates the bend angle based on the bit and ignores the pole_angle float for
the bend. An earlier exporter folded the flip into pole_angle and wrote the bit
as 0, so re-exported models bent the leg the wrong way in game. Compose must
write the 0x4 bit on the effector-length IK hint when pole_flip is set, and keep
the raw pole_angle on the joint2 hint.
"""
import types

from shared.IR.constraints import IRIKConstraint, IRBoneReposition
from shared.IR.skeleton import IRBone
from shared.IR.enums import ScaleInheritance
from shared.Constants.hsd import REFTYPE_IKHINT, ROBJ_TYPE_MASK
from shared.Nodes.Classes.Joints.BoneReference import BoneReference
from exporter.phases.compose.helpers.bones import compose_bones
from exporter.phases.compose.helpers.constraints import compose_constraints


def _identity():
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _bone(name, parent_index=None):
    return IRBone(
        name=name, parent_index=parent_index,
        position=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1),
        inverse_bind_matrix=None, flags=0, is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED, ik_shrink=False,
        world_matrix=_identity(), local_matrix=_identity(),
        normalized_world_matrix=_identity(), normalized_local_matrix=_identity(),
        scale_correction=_identity(), accumulated_scale=(1, 1, 1),
    )


def _ik_hints(joint):
    """Return [(flip_bit, pole_angle, length), ...] for the IK hints on a joint."""
    out = []
    ref = joint.reference
    while ref:
        if (ref.flags & ROBJ_TYPE_MASK) == REFTYPE_IKHINT and isinstance(ref.property, BoneReference):
            out.append((ref.flags & 0x4, ref.property.pole_angle, ref.property.length))
        ref = ref.next
    return out


def _compose(pole_flip):
    # grandparent(0) -> knee/joint2(1) -> effector(2)
    bones = [_bone('gp'), _bone('knee', 0), _bone('eff', 1)]
    _root, joints = compose_bones(bones)
    model = types.SimpleNamespace(
        ik_constraints=[IRIKConstraint(
            bone_name='eff', chain_length=3,
            target_bone=None, pole_target_bone=None,
            pole_angle=0.00068, pole_flip=pole_flip,
            bone_repositions=[IRBoneReposition('eff', 0.5),
                              IRBoneReposition('knee', 0.3)],
        )],
        copy_location_constraints=[], track_to_constraints=[],
        copy_rotation_constraints=[], limit_rotation_constraints=[],
        limit_location_constraints=[],
    )
    compose_constraints(model, joints, bones)
    return joints


def test_pole_flip_bit_written_on_knee_hint():
    joints = _compose(pole_flip=True)
    # The effector-length hint lives on the effector's parent (the knee) and is
    # the one the runtime reads the flip bit from.
    knee_hints = _ik_hints(joints[1])
    assert knee_hints, "expected an IK hint on the knee joint"
    flip_bit, pole_angle, _ = knee_hints[0]
    assert flip_bit == 0x4, "pole_flip must set the 0x4 bit on the knee's IK hint"
    assert pole_angle == 0.0, "the effector hint carries a zero pole_angle"


def test_pole_flip_clear_when_not_flipped():
    joints = _compose(pole_flip=False)
    flip_bit, _, _ = _ik_hints(joints[1])[0]
    assert flip_bit == 0, "no flip bit when pole_flip is False"


def test_raw_pole_angle_kept_on_joint2_hint():
    joints = _compose(pole_flip=True)
    # The joint2-length hint lives on the knee's parent (grandparent) and keeps
    # the raw pole angle, never the flip bit.
    gp_hints = _ik_hints(joints[0])
    assert gp_hints, "expected an IK hint on the grandparent joint"
    flip_bit, pole_angle, _ = gp_hints[0]
    assert flip_bit == 0
    assert abs(pole_angle - 0.00068) < 1e-6
