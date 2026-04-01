"""Compose placeholder animations for the export pipeline.

Creates a single-frame static rest pose animation for each bone,
ensuring the exported model has valid animation data. This prevents
crashes in games that expect animation slots to be populated.
"""
try:
    from .....shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
    from .....shared.Nodes.Classes.Animation.Animation import Animation
    from .....shared.Nodes.Classes.Animation.Frame import Frame
    from .....shared.Constants.hsd import (
        HSD_A_OP_CON, HSD_A_FRAC_FLOAT,
        HSD_A_J_ROTX, HSD_A_J_ROTY, HSD_A_J_ROTZ,
        HSD_A_J_TRAX, HSD_A_J_TRAY, HSD_A_J_TRAZ,
        HSD_A_J_SCAX, HSD_A_J_SCAY, HSD_A_J_SCAZ,
    )
    from .....shared.helpers.binary import pack_native
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
    from shared.Nodes.Classes.Animation.Animation import Animation
    from shared.Nodes.Classes.Animation.Frame import Frame
    from shared.Constants.hsd import (
        HSD_A_OP_CON, HSD_A_FRAC_FLOAT,
        HSD_A_J_ROTX, HSD_A_J_ROTY, HSD_A_J_ROTZ,
        HSD_A_J_TRAX, HSD_A_J_TRAY, HSD_A_J_TRAZ,
        HSD_A_J_SCAX, HSD_A_J_SCAY, HSD_A_J_SCAZ,
    )
    from shared.helpers.binary import pack_native
    from shared.helpers.logger import StubLogger


def compose_placeholder_animation(joints, bones, logger=StubLogger()):
    """Create a single-frame rest pose AnimationJoint tree.

    Mirrors the Joint tree structure with a constant keyframe at frame 0
    for each bone's rest pose SRT values. This provides valid animation
    data for games that expect animation slots to be populated.

    Args:
        joints: list[Joint] from compose_bones (indexed by bone index).
        bones: list[IRBone] from the IR (for rest pose SRT values).
        logger: Logger instance.

    Returns:
        AnimationJoint root, or None if no joints.
    """
    if not joints or not bones:
        return None

    # Create AnimationJoint nodes parallel to the Joint tree
    anim_joints = []
    for i, bone in enumerate(bones):
        anim_joint = AnimationJoint(address=None, blender_obj=None)
        anim_joint.child = None
        anim_joint.next = None
        anim_joint.render_animation = None
        anim_joint.flags = 0

        # Build animation with rest pose keyframes
        anim_joint.animation = _build_rest_pose_animation(bone, joints[i])
        anim_joints.append(anim_joint)

    # Reconstruct child/next tree from parent_index (same as compose_bones)
    from collections import defaultdict
    children_of = defaultdict(list)
    roots = []
    for i, bone in enumerate(bones):
        if bone.parent_index is None:
            roots.append(i)
        else:
            children_of[bone.parent_index].append(i)

    for parent_idx, child_indices in children_of.items():
        anim_joints[parent_idx].child = anim_joints[child_indices[0]]
        for j in range(1, len(child_indices)):
            anim_joints[child_indices[j - 1]].next = anim_joints[child_indices[j]]

    for j in range(1, len(roots)):
        anim_joints[roots[j - 1]].next = anim_joints[roots[j]]

    root = anim_joints[roots[0]] if roots else None

    logger.info("    Composed placeholder animation: %d bones, 1 frame (rest pose)", len(anim_joints))
    return root


def _build_rest_pose_animation(bone, joint):
    """Build an Animation node with constant keyframes at the bone's rest SRT."""
    anim = Animation(address=None, blender_obj=None)
    anim.flags = 0
    anim.end_frame = 1.0
    anim.joint = joint

    # Build Frame linked list for each SRT channel
    channels = [
        (HSD_A_J_ROTX, bone.rotation[0]),
        (HSD_A_J_ROTY, bone.rotation[1]),
        (HSD_A_J_ROTZ, bone.rotation[2]),
        (HSD_A_J_TRAX, bone.position[0]),
        (HSD_A_J_TRAY, bone.position[1]),
        (HSD_A_J_TRAZ, bone.position[2]),
        (HSD_A_J_SCAX, bone.scale[0]),
        (HSD_A_J_SCAY, bone.scale[1]),
        (HSD_A_J_SCAZ, bone.scale[2]),
    ]

    frames = []
    for channel_type, value in channels:
        frame = _build_constant_frame(channel_type, value)
        frames.append(frame)

    # Link frames into a linked list
    for i in range(len(frames) - 1):
        frames[i].next = frames[i + 1]

    anim.frame = frames[0] if frames else None
    return anim


def _build_constant_frame(channel_type, value):
    """Build a Frame node with a single constant keyframe.

    Encodes a single HSD_A_OP_CON keyframe with a float value at frame 0.
    The raw_ad encoding is:
        byte 0: opcode (HSD_A_OP_CON=1) | node_count_packed (0 = 1 node)
        bytes 1-4: float32 big-endian value
        byte 5: wait (0 = no more frames)
    """
    frame = Frame(address=None, blender_obj=None)
    frame.next = None
    frame.start_frame = 0.0
    frame.type = channel_type
    frame.frac_value = HSD_A_FRAC_FLOAT  # float encoding, 0 frac bits
    frame.frac_slope = HSD_A_FRAC_FLOAT
    frame.ad = 0  # pointer, set during writePrivateData

    # Encode raw_ad: opcode byte + float value + wait byte.
    # The decoder uses native byte order (Frame._read_node_values), so
    # we must encode with native byte order via pack_native.
    opcode_byte = HSD_A_OP_CON  # node_count bits = 0 (means 1 node)
    raw = bytearray()
    raw.append(opcode_byte)
    raw.extend(pack_native('float', value))
    raw.append(0)  # wait = 0 (single keyframe, no advance)

    frame.raw_ad = bytes(raw)
    frame.data_length = len(frame.raw_ad)

    return frame
