import struct
from ...Node import Node
from ....Constants import *
from ....IO.Logger import NullLogger

# Frame (aka FObject)
class Frame(Node):
    class_name = "Key Frame"
    fields = [
        ('next', 'Frame'),
        ('data_length', 'uint'),
        ('start_frame', 'float'),
        ('type', 'uchar'),
        ('frac_value', 'uchar'),
        ('frac_slope', 'uchar'),
        ('ad', 'uint'), # raw byte buffer; overwritten with bytes by loadFromBinary
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        if self.ad and self.data_length:
            self.raw_ad = parser.read_chunk(self.data_length, self.ad, parser._startOffset(True))
            parser.logger.debug("Frame 0x%X: type=%d, data_length=%d, start_frame=%.1f, frac_value=0x%02X, frac_slope=0x%02X, raw_ad=%s",
                                self.address, self.type, self.data_length, self.start_frame, self.frac_value, self.frac_slope,
                                ' '.join('%02X' % b for b in self.raw_ad))
        else:
            self.raw_ad = b''

    def writePrivateData(self, builder):
        super().writePrivateData(builder)
        if self.raw_ad:
            builder.seek(0, 'end')
            self.ad = builder._currentRelativeAddress()
            for byte in self.raw_ad:
                builder.write(byte, 'uchar')
            self._raw_pointer_fields.add('ad')
        else:
            self.ad = 0


_interpolation_dict = {
    HSD_A_OP_NONE: 'CONSTANT',
    HSD_A_OP_CON:  'CONSTANT',
    HSD_A_OP_LIN:  'LINEAR',
    HSD_A_OP_SPL0: 'BEZIER',
    HSD_A_OP_SPL:  'BEZIER',
    HSD_A_OP_KEY:  'LINEAR',
}


def read_fobjdesc(fobj, curve, bias, scale, logger=NullLogger()):
    """Decode the compressed keyframe byte stream and insert points into a Blender fcurve."""
    current_frame = 0 - fobj.start_frame // 1
    cur_pos = 0
    ad = fobj.raw_ad

    value_type = fobj.frac_value & HSD_A_FRAC_TYPE_MASK
    frac_value = fobj.frac_value & HSD_A_FRAC_MASK
    slope_type = fobj.frac_slope & HSD_A_FRAC_TYPE_MASK
    frac_slope  = fobj.frac_slope & HSD_A_FRAC_MASK

    keyframes = []
    slopes    = []
    cur_slope = 0

    while cur_pos < len(ad):
        opcode     = ad[cur_pos] & HSD_A_OP_MASK
        node_count = (ad[cur_pos] & HSD_A_PACK0_MASK) >> HSD_A_PACK0_SHIFT
        shift = 0
        while ad[cur_pos] & HSD_A_PACK_EXT:
            cur_pos += 1
            node_count += (ad[cur_pos] & HSD_A_PACK1_MASK) << (HSD_A_PACK1_BIT * shift + 3)
            shift += 1
        cur_pos += 1
        node_count += 1  # always at least one node

        logger.debug("      fobjdesc: opcode=%d node_count=%d cur_pos=%d", opcode, node_count, cur_pos)

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

                keyframe = curve.keyframe_points.insert(current_frame, (val + bias) * scale)
                keyframe.interpolation = _interpolation_dict.get(opcode, 'CONSTANT')
                keyframes.append(keyframe)

                if opcode != HSD_A_OP_NONE:
                    shift = 0
                    wait  = 0
                    while cur_pos < len(ad):
                        wait += (ad[cur_pos] & HSD_A_WAIT_MASK) << (HSD_A_WAIT_BIT * shift)
                        shift += 1
                        if not ad[cur_pos] & HSD_A_WAIT_EXT:
                            break
                        cur_pos += 1
                    cur_pos += 1
                    current_frame += wait

                logger.debug("      fobjdesc: insert frame=%.1f val=%.4f scaled=%.4f wait=%d cur_pos=%d",
                             keyframe.co[0], val, (val + bias) * scale,
                             wait if opcode != HSD_A_OP_NONE else 0, cur_pos)

    # Access keyframes through the curve's collection — stored references from
    # insert() become stale after subsequent inserts (Blender reallocates internally).
    kf_count = len(curve.keyframe_points)
    offset = kf_count - len(keyframes)
    for i in range(len(keyframes)):
        keyframe = curve.keyframe_points[offset + i]
        if i > 0:
            prev = curve.keyframe_points[offset + i - 1]
            l_delta = keyframe.co[0] - prev.co[0]
            keyframe.handle_left[:] = (
                keyframe.co[0] - l_delta / 3,
                keyframe.co[1] - slopes[i][0] * l_delta / 3,
            )
        if i < len(keyframes) - 1:
            nxt = curve.keyframe_points[offset + i + 1]
            r_delta = nxt.co[0] - keyframe.co[0]
            keyframe.handle_right[:] = (
                keyframe.co[0] + r_delta / 3,
                keyframe.co[1] + slopes[i][1] * r_delta / 3,
            )


def _read_node_values(opcode, value_type, frac_value, slope_type, frac_slope, ad, cur_pos):
    """Decode one value+slope from the compressed animation byte stream.
    Uses native byte order to match the reference implementation."""
    val   = 0
    slope = 0

    if opcode == HSD_A_OP_NONE:
        return 0, 0, cur_pos

    if opcode != HSD_A_OP_SLP:
        if value_type == HSD_A_FRAC_FLOAT:
            val = struct.unpack('f', ad[cur_pos:cur_pos + 4])[0]
            cur_pos += 4
        elif value_type == HSD_A_FRAC_S16:
            val = struct.unpack('h', ad[cur_pos:cur_pos + 2])[0] / (1 << frac_value)
            cur_pos += 2
        elif value_type == HSD_A_FRAC_U16:
            val = struct.unpack('H', ad[cur_pos:cur_pos + 2])[0] / (1 << frac_value)
            cur_pos += 2
        elif value_type == HSD_A_FRAC_S8:
            val = struct.unpack('b', ad[cur_pos:cur_pos + 1])[0] / (1 << frac_value)
            cur_pos += 1
        elif value_type == HSD_A_FRAC_U8:
            val = struct.unpack('B', ad[cur_pos:cur_pos + 1])[0] / (1 << frac_value)
            cur_pos += 1

    if opcode in (HSD_A_OP_SPL, HSD_A_OP_SLP):
        if slope_type == HSD_A_FRAC_FLOAT:
            slope = struct.unpack('f', ad[cur_pos:cur_pos + 4])[0]
            cur_pos += 4
        elif slope_type == HSD_A_FRAC_S16:
            slope = struct.unpack('h', ad[cur_pos:cur_pos + 2])[0] / (1 << frac_slope)
            cur_pos += 2
        elif slope_type == HSD_A_FRAC_U16:
            slope = struct.unpack('H', ad[cur_pos:cur_pos + 2])[0] / (1 << frac_slope)
            cur_pos += 2
        elif slope_type == HSD_A_FRAC_S8:
            slope = struct.unpack('b', ad[cur_pos:cur_pos + 1])[0] / (1 << frac_slope)
            cur_pos += 1
        elif slope_type == HSD_A_FRAC_U8:
            slope = struct.unpack('B', ad[cur_pos:cur_pos + 1])[0] / (1 << frac_slope)
            cur_pos += 1

    return val, slope, cur_pos
