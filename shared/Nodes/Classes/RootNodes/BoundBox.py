from ...Node import Node

# Bound Box
# Contains per-animation-set, per-frame axis-aligned bounding boxes (AABBs).
# Structure:
#   ushort  anim_set_count    — number of animation sets (matches ModelSet.animated_joints length)
#   uint    unknown           — frame count of the first animation set (end_frame + 1)
#   [inline AABB data]        — (total_frames × 24 bytes) of min/max vec3 pairs,
#                               one AABB per frame per animation set, concatenated
#
# The AABB data size cannot be determined from the BoundBox fields alone —
# it depends on the animation frame counts. For round-trip, we store all
# remaining bytes from the struct end to the data section end.
class BoundBox(Node):
    class_name = "Bound Box"
    fields = [
        ('anim_set_count', 'ushort'),
        ('unknown', 'uint'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        # Read all remaining data from the end of this struct to the end of the data section.
        # This contains per-frame AABB data (24 bytes per frame: min vec3 + max vec3).
        # The data section is 16-byte aligned, so trailing bytes may be padding.
        struct_end = self.address + 8  # ushort(2) + pad(2) + uint(4)
        data_section_end = parser.header.data_size
        trailing_size = data_section_end - struct_end
        if trailing_size > 0:
            raw = parser.read_chunk(trailing_size, struct_end, parser._startOffset(True))
            # Trim to the last 24-byte AABB boundary (strip alignment padding)
            aabb_count = trailing_size // 24
            self.raw_aabb_data = raw[:aabb_count * 24]
        else:
            self.raw_aabb_data = b''

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

