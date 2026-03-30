"""Compose IRBone list into a Joint node tree.

Reverses importer/phases/describe/helpers/bones.py:describe_bones().
Takes a flat list of IRBone dataclasses and reconstructs the Joint
child/next sibling tree structure used by the DAT format.
"""
from collections import defaultdict

try:
    from ......shared.Nodes.Classes.Joints.Joint import Joint
    from ......shared.Constants.hsd import JOBJ_INSTANCE
    from ......shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Joints.Joint import Joint
    from shared.Constants.hsd import JOBJ_INSTANCE
    from shared.helpers.logger import StubLogger


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
        joint.inverse_bind = bone.inverse_bind_matrix
        joint.property = None
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

    logger.info("Composed %d bones into Joint tree", len(joints))

    return root_joint, joints
