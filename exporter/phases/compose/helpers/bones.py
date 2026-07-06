"""Compose IRBone list into a Joint node tree.

Reverses importer/phases/describe/helpers/bones.py:describe_bones().
Takes a flat list of IRBone dataclasses and reconstructs the Joint
child/next sibling tree structure used by the DAT format.
"""
from collections import defaultdict

try:
    from .....shared.Nodes.Classes.Joints.Joint import Joint
    from .....shared.Nodes.Classes.Misc.Spline import Spline
    from .....shared.Constants.hsd import JOBJ_INSTANCE
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Joints.Joint import Joint
    from shared.Nodes.Classes.Misc.Spline import Spline
    from shared.Constants.hsd import JOBJ_INSTANCE
    from shared.helpers.logger import StubLogger


def _compose_joint_spline(bone):
    """Rebuild a Spline node from a bone's IRBoneSpline, or None.

    The Spline serializer writes its s1/s2/s3 arrays from Python lists, so we
    hand the resolved control-point / knot / coefficient lists straight back.
    Values are already in GC units (carried verbatim through the IR).
    """
    ir_spline = getattr(bone, 'spline', None)
    if ir_spline is None:
        return None

    spline = Spline(address=None, blender_obj=None)
    spline.flags = ir_spline.flags
    spline.n = ir_spline.n
    spline.f0 = ir_spline.f0
    spline.f1 = ir_spline.f1
    spline.s1 = [list(p) for p in ir_spline.control_points] if ir_spline.control_points else None
    spline.s2 = list(ir_spline.knots) if ir_spline.knots else None
    spline.s3 = [list(c) for c in ir_spline.coefficients] if ir_spline.coefficients else None
    return spline


def compose_bones(bones, logger=StubLogger()):
    """Convert a flat IRBone list into a Joint tree.

    Args:
        bones: list[IRBone] from describe_bones().
        logger: Logger instance.

    Returns:
        (root_joint, joints) — the root Joint node and a list of all
        Joint nodes indexed by bone index (for mesh attachment later).
    """
    if not bones:
        return None, []

    # Step 1: Create Joint nodes from IRBone list
    joints = []
    for bone in bones:
        joint = Joint(address=None, blender_obj=None)
        joint.name = bone.name
        joint.flags = bone.flags
        joint.position = list(bone.position)
        joint.rotation = list(bone.rotation)
        joint.scale = list(bone.scale)
        joint.inverse_bind = (
            [list(row) for row in bone.inverse_bind_matrix]
            if bone.inverse_bind_matrix is not None else None
        )
        joint.property = _compose_joint_spline(bone)
        joint.reference = None
        joint.child = None
        joint.next = None
        joints.append(joint)

    # Step 2: Reconstruct child/next tree from parent_index
    children_of = defaultdict(list)
    roots = []
    for i, bone in enumerate(bones):
        if bone.parent_index is None:
            roots.append(i)
        else:
            children_of[bone.parent_index].append(i)

    # Link children: first child → parent.child, rest → previous.next
    for parent_idx, child_indices in children_of.items():
        joints[parent_idx].child = joints[child_indices[0]]
        for j in range(1, len(child_indices)):
            joints[child_indices[j - 1]].next = joints[child_indices[j]]

    # Link root siblings via .next
    for j in range(1, len(roots)):
        joints[roots[j - 1]].next = joints[roots[j]]

    # Step 3: Handle JOBJ_INSTANCE bones
    for i, bone in enumerate(bones):
        if bone.instance_child_bone_index is not None:
            joints[i].child = joints[bone.instance_child_bone_index]

    root_joint = joints[roots[0]] if roots else None

    instance_count = sum(1 for b in bones if b.instance_child_bone_index is not None)
    logger.info("    Composed %d bones into Joint tree (%d root(s), %d instance(s))",
                len(joints), len(roots), instance_count)

    return root_joint, joints
