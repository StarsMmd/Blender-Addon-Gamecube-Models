import struct

from ...Node import Node

# Bound Box
# Contains per-animation-set, per-frame axis-aligned bounding boxes (AABBs).
# Struct fields:
#   ushort  anim_set_count    — number of animation sets (matches ModelSet.animated_joints length)
#   uint    first_anim_frame_count — frame count of the FIRST animation set (end_frame + 1)
# Inline trailing data — one 24-byte AABB (min vec3 + max vec3, big-endian
# float32) per frame, grouped by animation set:
#   [set 0: first_anim_frame_count × 24 bytes]
#   [set i>0: uint32 frame_count][frame_count × 24 bytes]   (repeated)
# i.e. every set AFTER the first is prefixed by its own uint32 frame count;
# set 0's count lives in the struct field. The total length therefore is NOT a
# plain multiple of 24 once there is more than one set.
class BoundBox(Node):
    class_name = "Bound Box"
    fields = [
        ('anim_set_count', 'ushort'),
        ('first_anim_frame_count', 'uint'),
    ]

    @staticmethod
    def iter_frames(raw, anim_set_count, first_count):
        """Yield the 24-byte AABB chunks from a structured bound-box blob,
        skipping the uint32 frame-count prefix that precedes every set after
        the first. Stops cleanly if the buffer ends mid-structure (the parsed
        blob may be alignment-trimmed)."""
        pos = 0
        n = len(raw)
        for s in range(max(1, anim_set_count)):
            if s == 0:
                count = first_count
            else:
                if pos + 4 > n:
                    return
                count = struct.unpack('>I', raw[pos:pos + 4])[0]
                pos += 4
            for _ in range(count):
                if pos + 24 > n:
                    return
                yield raw[pos:pos + 24]
                pos += 24

    @staticmethod
    def build_blob(per_set_frames):
        """Build a structured bound-box blob from per-set lists of 24-byte AABB
        chunks. Set 0 is written flat; each later set is prefixed by its uint32
        frame count — the inverse of iter_frames()."""
        out = bytearray()
        for s, frames in enumerate(per_set_frames):
            if s > 0:
                out += struct.pack('>I', len(frames))
            for chunk in frames:
                out += chunk
        return bytes(out)

    @staticmethod
    def _layout_length(raw, anim_set_count, first_count):
        """Exact byte length of the structured AABB data (set 0 flat, each later
        set prefixed by a uint32 count), excluding trailing alignment padding.
        Returns None if the declared layout doesn't fit the buffer."""
        pos = 0
        n = len(raw)
        for s in range(max(1, anim_set_count)):
            if s == 0:
                count = first_count
            else:
                if pos + 4 > n:
                    return None
                count = struct.unpack('>I', raw[pos:pos + 4])[0]
                pos += 4
            if count < 0 or pos + count * 24 > n:
                return None
            pos += count * 24
        return pos

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        # Read all remaining data from the end of this struct to the end of the
        # data section, then trim to the exact AABB layout (the per-set count
        # prefixes mean the real length is not a plain multiple of 24, and the
        # data section is 16-byte aligned so the tail also carries padding).
        struct_end = self.address + 8  # ushort(2) + pad(2) + uint(4)
        data_section_end = parser.header.data_size
        trailing_size = data_section_end - struct_end
        if trailing_size <= 0:
            self.raw_aabb_data = b''
            return
        raw = parser.read_chunk(trailing_size, struct_end, parser._startOffset(True))
        consumed = self._layout_length(raw, self.anim_set_count, self.first_anim_frame_count)
        if consumed is None:
            # Layout didn't validate — fall back to a flat 24-byte trim.
            consumed = (trailing_size // 24) * 24
        self.raw_aabb_data = raw[:consumed]

    def allocationSize(self):
        return super().allocationSize() + len(getattr(self, 'raw_aabb_data', b''))

    def writePrimitivePointers(self, builder):
        super().writePrimitivePointers(builder)
        # AABB data is written inline after the struct, not as a separate pointer.
        # It will be written in writeBinary.

    def writeBinary(self, builder):
        if self.address is None:
            return
        builder.writeNode(self, relative_to_header=True)
        # Write AABB data immediately after the struct fields
        if hasattr(self, 'raw_aabb_data') and self.raw_aabb_data:
            for byte in self.raw_aabb_data:
                builder.file.write(bytes([byte]))

