"""Compose IRBoneAnimationSet into AnimationJoint node trees.

Encodes IRKeyframe lists into HSD compressed byte streams (Frame.raw_ad)
and builds the AnimationJoint/Animation/Frame node tree structure that
parallels the Joint skeleton tree.
"""
from collections import defaultdict

try:
    from .....shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
    from .....shared.Nodes.Classes.Animation.Animation import Animation
    from .....shared.Nodes.Classes.Animation.Frame import Frame
    from .....shared.Constants.hsd import (
        HSD_A_OP_NONE, HSD_A_OP_CON, HSD_A_OP_LIN, HSD_A_FRAC_FLOAT,
        HSD_A_J_ROTX, HSD_A_J_ROTY, HSD_A_J_ROTZ,
        HSD_A_J_TRAX, HSD_A_J_TRAY, HSD_A_J_TRAZ,
        HSD_A_J_SCAX, HSD_A_J_SCAY, HSD_A_J_SCAZ,
        AOBJ_ANIM_LOOP,
    )
    from .....shared.IR.enums import Interpolation
    from .....shared.helpers.binary import pack_native
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
    from shared.Nodes.Classes.Animation.Animation import Animation
    from shared.Nodes.Classes.Animation.Frame import Frame
    from shared.Constants.hsd import (
        HSD_A_OP_NONE, HSD_A_OP_CON, HSD_A_OP_LIN, HSD_A_FRAC_FLOAT,
        HSD_A_J_ROTX, HSD_A_J_ROTY, HSD_A_J_ROTZ,
        HSD_A_J_TRAX, HSD_A_J_TRAY, HSD_A_J_TRAZ,
        HSD_A_J_SCAX, HSD_A_J_SCAY, HSD_A_J_SCAZ,
        AOBJ_ANIM_LOOP,
    )
    from shared.IR.enums import Interpolation
    from shared.helpers.binary import pack_native
    from shared.helpers.logger import StubLogger


# Channel type constants for each SRT component
_CHANNEL_TYPES = [
    HSD_A_J_ROTX, HSD_A_J_ROTY, HSD_A_J_ROTZ,
    HSD_A_J_TRAX, HSD_A_J_TRAY, HSD_A_J_TRAZ,
    HSD_A_J_SCAX, HSD_A_J_SCAY, HSD_A_J_SCAZ,
]

# Map IR interpolation to HSD opcode
_INTERP_TO_OPCODE = {
    Interpolation.CONSTANT: HSD_A_OP_CON,
    Interpolation.LINEAR: HSD_A_OP_LIN,
    Interpolation.BEZIER: HSD_A_OP_LIN,  # Encode bezier as linear for now
}


def compose_bone_animations(bone_animations, joints, bones, logger=StubLogger()):
    """Convert IRBoneAnimationSet list into AnimationJoint tree roots.

    Args:
        bone_animations: list[IRBoneAnimationSet] from describe phase.
        joints: list[Joint] from compose_bones.
        bones: list[IRBone] from IR.
        logger: Logger instance.

    Returns:
        list[AnimationJoint] — one root per animation set, or None if empty.
    """
    if not bone_animations or not joints:
        return None

    results = []
    for anim_set in bone_animations:
        root = _compose_anim_set(anim_set, joints, bones, logger)
        if root is not None:
            results.append(root)

    if results:
        logger.info("    Composed %d animation set(s)", len(results))

    return results if results else None


def _compose_anim_set(anim_set, joints, bones, logger):
    """Build an AnimationJoint tree for one IRBoneAnimationSet."""
    # Index tracks by bone index for quick lookup
    track_by_bone = {}
    for track in anim_set.tracks:
        track_by_bone[track.bone_index] = track

    # Create AnimationJoint nodes for every bone
    anim_joints = []
    for i, bone in enumerate(bones):
        aj = AnimationJoint(address=None, blender_obj=None)
        aj.child = None
        aj.next = None
        aj.render_animation = None
        aj.flags = 0

        track = track_by_bone.get(i)
        if track:
            aj.animation = _build_animation(track, joints[i], anim_set.loop)
        else:
            aj.animation = None

        anim_joints.append(aj)

    # Reconstruct child/next tree from parent_index
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

    return anim_joints[roots[0]] if roots else None


def _build_animation(track, joint, loop):
    """Build an Animation node from an IRBoneTrack."""
    anim = Animation(address=None, blender_obj=None)
    anim.flags = AOBJ_ANIM_LOOP if loop else 0
    anim.end_frame = float(track.end_frame)
    anim.joint = joint

    # Build Frame linked list for each SRT channel
    frames = []
    all_channels = (
        list(track.rotation) +   # [X, Y, Z]
        list(track.location) +   # [X, Y, Z]
        list(track.scale)        # [X, Y, Z]
    )

    for ch_idx, keyframes in enumerate(all_channels):
        if not keyframes:
            continue
        channel_type = _CHANNEL_TYPES[ch_idx]
        frame = _encode_channel(keyframes, channel_type)
        if frame is not None:
            frames.append(frame)

    # Link frames into list
    for i in range(len(frames) - 1):
        frames[i].next = frames[i + 1]

    anim.frame = frames[0] if frames else None
    return anim


def _encode_channel(keyframes, channel_type):
    """Encode a list of IRKeyframe into a Frame node with raw_ad bytes.

    Groups consecutive keyframes by interpolation type and encodes them
    into the HSD compressed byte format.
    """
    if not keyframes:
        return None

    frame = Frame(address=None, blender_obj=None)
    frame.next = None
    frame.start_frame = 0.0
    frame.type = channel_type
    frame.frac_value = HSD_A_FRAC_FLOAT
    frame.frac_slope = HSD_A_FRAC_FLOAT
    frame.ad = 0

    raw = bytearray()

    # Encode keyframes in groups by interpolation type
    i = 0
    while i < len(keyframes):
        kf = keyframes[i]
        opcode = _INTERP_TO_OPCODE.get(kf.interpolation, HSD_A_OP_LIN)

        # Count consecutive keyframes with the same interpolation
        run_start = i
        while i < len(keyframes) and _INTERP_TO_OPCODE.get(keyframes[i].interpolation, HSD_A_OP_LIN) == opcode:
            i += 1
        run_count = i - run_start

        # Encode the opcode + node count
        _encode_opcode(raw, opcode, run_count)

        # Encode each keyframe's value + wait
        for j in range(run_start, run_start + run_count):
            kf = keyframes[j]
            raw.extend(pack_native('float', kf.value))

            if opcode != HSD_A_OP_NONE:
                # Wait = frame delta to next keyframe
                if j + 1 < len(keyframes):
                    wait = int(keyframes[j + 1].frame - kf.frame)
                else:
                    wait = 0
                _encode_wait(raw, wait)

    frame.raw_ad = bytes(raw)
    frame.data_length = len(frame.raw_ad)
    return frame


def _encode_opcode(raw, opcode, node_count):
    """Encode an opcode byte with packed node count.

    node_count is decremented by 1 (the format stores count-1).
    """
    count = node_count - 1

    # Pack count into the opcode byte (3 bits in bits 4-6)
    first_byte = opcode | ((min(count, 7)) << 4)

    remaining = count - min(count, 7)
    if remaining > 0:
        first_byte |= 0x80  # extension flag
        raw.append(first_byte)

        # Extension bytes (7 bits each, MSB = continue flag)
        while remaining > 0:
            ext_byte = remaining & 0x7F
            remaining >>= 7
            if remaining > 0:
                ext_byte |= 0x80
            raw.append(ext_byte)
    else:
        raw.append(first_byte)


def _encode_wait(raw, wait):
    """Encode a frame wait value into the byte stream.

    Uses variable-length encoding with 7-bit chunks and extension flag.
    """
    if wait == 0:
        raw.append(0)
        return

    while True:
        byte = wait & 0x7F  # 7 data bits
        wait >>= 7
        if wait > 0:
            byte |= 0x80  # extension flag
        raw.append(byte)
        if wait == 0:
            break
