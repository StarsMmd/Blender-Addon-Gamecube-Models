"""Pure-data keyframe decoder for HSD compressed animation streams.

Decodes the opcode-packed keyframe byte format into IRKeyframe dataclasses.
No Blender dependency — uses only the IR types and binary helpers.
"""
try:
    from .....shared.helpers.binary import read_native
    from .....shared.IR.animation import IRKeyframe
    from .....shared.IR.enums import Interpolation
    from .....shared.Constants.hsd import (
        HSD_A_OP_MASK, HSD_A_OP_NONE, HSD_A_OP_CON, HSD_A_OP_LIN,
        HSD_A_OP_SPL0, HSD_A_OP_SPL, HSD_A_OP_KEY, HSD_A_OP_SLP,
        HSD_A_PACK0_MASK, HSD_A_PACK0_SHIFT, HSD_A_PACK_EXT,
        HSD_A_PACK1_MASK, HSD_A_PACK1_BIT,
        HSD_A_WAIT_MASK, HSD_A_WAIT_BIT, HSD_A_WAIT_EXT,
        HSD_A_FRAC_TYPE_MASK, HSD_A_FRAC_MASK,
        HSD_A_FRAC_FLOAT, HSD_A_FRAC_S16, HSD_A_FRAC_U16,
        HSD_A_FRAC_S8, HSD_A_FRAC_U8,
    )
except (ImportError, SystemError):
    from shared.helpers.binary import read_native
    from shared.IR.animation import IRKeyframe
    from shared.IR.enums import Interpolation
    from shared.Constants.hsd import (
        HSD_A_OP_MASK, HSD_A_OP_NONE, HSD_A_OP_CON, HSD_A_OP_LIN,
        HSD_A_OP_SPL0, HSD_A_OP_SPL, HSD_A_OP_KEY, HSD_A_OP_SLP,
        HSD_A_PACK0_MASK, HSD_A_PACK0_SHIFT, HSD_A_PACK_EXT,
        HSD_A_PACK1_MASK, HSD_A_PACK1_BIT,
        HSD_A_WAIT_MASK, HSD_A_WAIT_BIT, HSD_A_WAIT_EXT,
        HSD_A_FRAC_TYPE_MASK, HSD_A_FRAC_MASK,
        HSD_A_FRAC_FLOAT, HSD_A_FRAC_S16, HSD_A_FRAC_U16,
        HSD_A_FRAC_S8, HSD_A_FRAC_U8,
    )

_INTERPOLATION_MAP = {
    HSD_A_OP_NONE: Interpolation.CONSTANT,
    HSD_A_OP_CON:  Interpolation.CONSTANT,
    HSD_A_OP_LIN:  Interpolation.LINEAR,
    HSD_A_OP_SPL0: Interpolation.BEZIER,
    HSD_A_OP_SPL:  Interpolation.BEZIER,
    HSD_A_OP_KEY:  Interpolation.LINEAR,
}


def decode_fobjdesc(fobj, bias=0, scale=1):
    """Decode an HSD compressed keyframe stream into a list of IRKeyframe.

    Args:
        fobj: A parsed Frame node with raw_ad, start_frame, frac_value, frac_slope.
        bias: Value offset (added before scaling).
        scale: Value multiplier.

    Returns:
        list[IRKeyframe] with frame positions, values, interpolation types,
        and pre-computed bezier handle coordinates.
    """
    ad = fobj.raw_ad
    if not ad:
        return []

    current_frame = 0 - fobj.start_frame // 1
    cur_pos = 0

    value_type = fobj.frac_value & HSD_A_FRAC_TYPE_MASK
    frac_value = fobj.frac_value & HSD_A_FRAC_MASK
    slope_type = fobj.frac_slope & HSD_A_FRAC_TYPE_MASK
    frac_slope = fobj.frac_slope & HSD_A_FRAC_MASK

    decoded = []  # (frame, value, interpolation)
    slopes = []   # (slope_in, slope_out) per keyframe
    cur_slope = 0

    while cur_pos < len(ad):
        opcode = ad[cur_pos] & HSD_A_OP_MASK
        node_count = (ad[cur_pos] & HSD_A_PACK0_MASK) >> HSD_A_PACK0_SHIFT
        shift = 0
        while ad[cur_pos] & HSD_A_PACK_EXT:
            cur_pos += 1
            node_count += (ad[cur_pos] & HSD_A_PACK1_MASK) << (HSD_A_PACK1_BIT * shift + 3)
            shift += 1
        cur_pos += 1
        node_count += 1

        if opcode == HSD_A_OP_SLP:
            for _ in range(node_count):
                if cur_pos >= len(ad):
                    break
                _, cur_slope, cur_pos = _read_node_values(
                    opcode, value_type, frac_value, slope_type, frac_slope, ad, cur_pos)
        else:
            for _ in range(node_count):
                if cur_pos >= len(ad):
                    break
                val, slope, cur_pos = _read_node_values(
                    opcode, value_type, frac_value, slope_type, frac_slope, ad, cur_pos)
                slopes.append((cur_slope, slope))
                cur_slope = slope

                interp = _INTERPOLATION_MAP.get(opcode, Interpolation.CONSTANT)
                scaled_val = (val + bias) * scale
                decoded.append((current_frame, scaled_val, interp))

                if opcode != HSD_A_OP_NONE:
                    shift = 0
                    wait = 0
                    while cur_pos < len(ad):
                        wait += (ad[cur_pos] & HSD_A_WAIT_MASK) << (HSD_A_WAIT_BIT * shift)
                        shift += 1
                        if not ad[cur_pos] & HSD_A_WAIT_EXT:
                            break
                        cur_pos += 1
                    cur_pos += 1
                    current_frame += wait

    # Build IRKeyframes with bezier handles computed from slopes
    keyframes = []
    for i, (frame, value, interp) in enumerate(decoded):
        handle_left = None
        handle_right = None

        if i > 0:
            prev_frame = decoded[i - 1][0]
            l_delta = frame - prev_frame
            handle_left = (frame - l_delta / 3, value - slopes[i][0] * l_delta / 3)

        if i < len(decoded) - 1:
            next_frame = decoded[i + 1][0]
            r_delta = next_frame - frame
            handle_right = (frame + r_delta / 3, value + slopes[i][1] * r_delta / 3)

        keyframes.append(IRKeyframe(
            frame=frame,
            value=value,
            interpolation=interp,
            handle_left=handle_left,
            handle_right=handle_right,
        ))

    return keyframes


def _read_node_values(opcode, value_type, frac_value, slope_type, frac_slope, ad, cur_pos):
    """Decode one value+slope from the compressed animation byte stream."""
    val = 0
    slope = 0

    if opcode == HSD_A_OP_NONE:
        return 0, 0, cur_pos

    if opcode != HSD_A_OP_SLP:
        val, cur_pos = _read_typed_value(value_type, frac_value, ad, cur_pos)

    if opcode in (HSD_A_OP_SPL, HSD_A_OP_SLP):
        slope, cur_pos = _read_typed_value(slope_type, frac_slope, ad, cur_pos)

    return val, slope, cur_pos


_FRAC_TYPE_INFO = {
    HSD_A_FRAC_FLOAT: ('float', 4, False),
    HSD_A_FRAC_S16:   ('short', 2, True),
    HSD_A_FRAC_U16:   ('ushort', 2, True),
    HSD_A_FRAC_S8:    ('char', 1, True),
    HSD_A_FRAC_U8:    ('uchar', 1, True),
}


def _read_typed_value(type_flag, frac_bits, ad, cur_pos):
    """Read a single value from the byte stream based on type encoding."""
    info = _FRAC_TYPE_INFO.get(type_flag)
    if info is None:
        return 0, cur_pos

    type_name, size, use_frac = info
    val = read_native(type_name, ad, cur_pos)
    if use_frac:
        val /= (1 << frac_bits)
    return val, cur_pos + size
