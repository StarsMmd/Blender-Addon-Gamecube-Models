"""Compose IRBoneAnimationSet into AnimationJoint node trees.

Encodes IRKeyframe lists into HSD compressed byte streams (Frame.raw_ad)
and builds the AnimationJoint/Animation/Frame node tree structure that
parallels the Joint skeleton tree.
"""
import math
from collections import defaultdict

try:
    from .....shared.Nodes.Classes.Animation.AnimationJoint import AnimationJoint
    from .....shared.Nodes.Classes.Animation.Animation import Animation
    from .....shared.Nodes.Classes.Animation.Frame import Frame
    from .....shared.Constants.hsd import (
        HSD_A_OP_NONE, HSD_A_OP_CON, HSD_A_OP_LIN,
        HSD_A_OP_SPL0, HSD_A_OP_SPL, HSD_A_OP_SLP,
        HSD_A_FRAC_FLOAT, HSD_A_FRAC_S16, HSD_A_FRAC_U16,
        HSD_A_FRAC_S8, HSD_A_FRAC_U8, HSD_A_FRAC_TYPE_MASK,
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
        HSD_A_OP_NONE, HSD_A_OP_CON, HSD_A_OP_LIN,
        HSD_A_OP_SPL0, HSD_A_OP_SPL, HSD_A_OP_SLP,
        HSD_A_FRAC_FLOAT, HSD_A_FRAC_S16, HSD_A_FRAC_U16,
        HSD_A_FRAC_S8, HSD_A_FRAC_U8, HSD_A_FRAC_TYPE_MASK,
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

_INTERP_TO_OPCODE_NO_SLOPE = {
    Interpolation.CONSTANT: HSD_A_OP_CON,
    Interpolation.LINEAR: HSD_A_OP_LIN,
    Interpolation.BEZIER: HSD_A_OP_LIN,  # Fallback when no slope data
}

_INTERP_TO_OPCODE_WITH_SLOPE = {
    Interpolation.CONSTANT: HSD_A_OP_CON,
    Interpolation.LINEAR: HSD_A_OP_LIN,
    Interpolation.BEZIER: HSD_A_OP_SPL,
}

# Quantization candidates ordered smallest to largest.
# Each entry: (type_flag, type_name_for_pack_native, min_val, max_val)
_QUANT_CANDIDATES = [
    (HSD_A_FRAC_U8,  'uchar',  0,      255),
    (HSD_A_FRAC_S8,  'char',   -128,   127),
    (HSD_A_FRAC_U16, 'ushort', 0,      65535),
    (HSD_A_FRAC_S16, 'short',  -32768, 32767),
]


def _pick_quantization(values, channel_type=None):
    """Pick the smallest quantization format for a set of float values.

    Uses the formula frac_bits = type_bits - ceil(log2(max_abs + 1))
    to compute the optimal fractional precision for each type, then
    verifies all values fit within tolerance. This matches the Colo/XD
    compiler's behavior of maximizing precision within the type's range.

    Note: HSDLib (Melee) uses a different strategy (lowest frac_bits
    first), but Colo/XD binaries consistently use higher frac_bits.

    Args:
        values: iterable of float values to encode.
        channel_type: HSD_A_J_* constant (reserved for future use).

    Returns:
        (frac_byte, pack_type) where frac_byte is the combined type|frac_bits
        byte, and pack_type is the type name for pack_native.
    """
    vals = [v for v in values if v is not None]
    if not vals:
        return HSD_A_FRAC_FLOAT, 'float'

    max_abs = max(abs(v) for v in vals)
    has_negative = min(vals) < -1e-6

    # Integer bits needed: ceil(log2(max_abs + 1)).
    if max_abs > 1e-6:
        int_bits = math.ceil(math.log2(max_abs + 1))
    else:
        int_bits = 0  # All values near zero

    for type_flag, pack_type, type_min, type_max in _QUANT_CANDIDATES:
        # Skip unsigned types if there are negative values
        if type_min >= 0 and has_negative:
            continue

        # Total usable bits: 8 for u8/s8 types, 16 for u16/s16 types
        # Signed types lose 1 bit to the sign
        if type_max <= 255:
            total_bits = 7 if type_min < 0 else 8
        else:
            total_bits = 15 if type_min < 0 else 16

        frac_bits = total_bits - int_bits
        if frac_bits < 0 or frac_bits > 31:
            continue

        # Verify all values fit in range AND precision is adequate.
        # Tolerance of 0.004 matches the Colo/XD compiler's behavior:
        # U8:7 (max error 0.0039) passes, U8:6 (max error 0.0078) gets
        # rejected for non-trivial values, pushing to wider types.
        scale = 1 << frac_bits
        tolerance = 0.004
        fits = True
        for v in vals:
            q = round(v * scale)
            if q < type_min or q > type_max:
                fits = False
                break
            if abs(v - q / scale) > tolerance:
                fits = False
                break
        if fits:
            return type_flag | frac_bits, pack_type

    return HSD_A_FRAC_FLOAT, 'float'


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
            aj.animation = _build_animation(track, anim_set.loop)
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


def _build_animation(track, loop):
    """Build an Animation node from an IRBoneTrack."""
    anim = Animation(address=None, blender_obj=None)
    anim.flags = AOBJ_ANIM_LOOP if loop else 0
    anim.end_frame = float(track.end_frame)
    anim.joint = None  # Not set in original binaries

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

    # Determine if any keyframes have slope data (from HSD import).
    # When slopes are present, BEZIER keyframes encode as SPL with slope
    # values. Without slopes (e.g. from Blender export), BEZIER falls
    # back to LIN.
    has_slopes = any(kf.slope_out is not None for kf in keyframes)
    opcode_map = _INTERP_TO_OPCODE_WITH_SLOPE if has_slopes else _INTERP_TO_OPCODE_NO_SLOPE

    # Pick optimal quantization for values and slopes
    frac_value, val_pack = _pick_quantization(kf.value for kf in keyframes)
    if has_slopes:
        all_slopes = []
        for kf in keyframes:
            if kf.slope_in is not None:
                all_slopes.append(kf.slope_in)
            if kf.slope_out is not None:
                all_slopes.append(kf.slope_out)
        frac_slope, slope_pack = _pick_quantization(all_slopes)
    else:
        frac_slope, slope_pack = HSD_A_FRAC_FLOAT, 'float'

    val_frac_bits = frac_value & 0x1F
    slope_frac_bits = frac_slope & 0x1F
    val_is_float = (frac_value & HSD_A_FRAC_TYPE_MASK) == HSD_A_FRAC_FLOAT
    slope_is_float = (frac_slope & HSD_A_FRAC_TYPE_MASK) == HSD_A_FRAC_FLOAT

    frame = Frame(address=None, blender_obj=None)
    frame.next = None
    frame.start_frame = float(-keyframes[0].frame)
    frame.type = channel_type
    frame.frac_value = frac_value
    frame.frac_slope = frac_slope
    frame.ad = 0

    raw = bytearray()

    # Encode keyframes in groups by interpolation type
    i = 0
    cur_slope = 0.0  # tracks the last emitted slope_out
    while i < len(keyframes):
        kf = keyframes[i]
        opcode = opcode_map.get(kf.interpolation, HSD_A_OP_LIN)

        # Count consecutive keyframes with the same opcode
        run_start = i
        while i < len(keyframes) and opcode_map.get(keyframes[i].interpolation, HSD_A_OP_LIN) == opcode:
            i += 1
        run_count = i - run_start

        # For SPL runs: if the first keyframe's slope_in differs from
        # cur_slope, emit an SLP preamble to set the incoming tangent.
        if opcode == HSD_A_OP_SPL:
            first_slope_in = keyframes[run_start].slope_in or 0.0
            if first_slope_in != cur_slope:
                _encode_opcode(raw, HSD_A_OP_SLP, 1)
                _encode_typed_value(raw, first_slope_in, slope_pack, slope_frac_bits, slope_is_float)
                cur_slope = first_slope_in

        # Encode the opcode + node count
        _encode_opcode(raw, opcode, run_count)

        # Encode each keyframe's value [+ slope] + wait
        for j in range(run_start, run_start + run_count):
            kf = keyframes[j]
            _encode_typed_value(raw, kf.value, val_pack, val_frac_bits, val_is_float)

            if opcode == HSD_A_OP_SPL:
                slope_out = kf.slope_out if kf.slope_out is not None else 0.0
                _encode_typed_value(raw, slope_out, slope_pack, slope_frac_bits, slope_is_float)
                cur_slope = slope_out

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


def _encode_typed_value(raw, value, pack_type, frac_bits, is_float):
    """Encode a value using the selected quantization format."""
    if is_float:
        raw.extend(pack_native('float', value))
    else:
        quantized = round(value * (1 << frac_bits))
        raw.extend(pack_native(pack_type, quantized))


def _encode_opcode(raw, opcode, node_count):
    """Encode an opcode byte with packed node count.

    The first byte stores the opcode in bits 0-2 and the bottom 3 bits
    of (count-1) in bits 4-6. Extension bytes store subsequent 7-bit
    chunks. The decoder reconstructs: count = first_3 + (ext << 3) + 1.
    """
    count = node_count - 1

    # First byte: opcode (bits 0-2) + bottom 3 bits of count (bits 4-6)
    first_3 = count & 7
    remaining = count >> 3

    first_byte = opcode | (first_3 << 4)
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
