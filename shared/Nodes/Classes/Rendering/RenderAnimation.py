from ...Node import Node

# Render Animation (HSD RObjAnim)
# Variable-size struct used for render object animations. The exact field layout
# depends on the animation type and is not yet fully reverse-engineered.
#
# For round-trip: we store the raw size so the node gets a valid allocation.
# The data is written as zeros (stub) since the internal pointer fields would
# need full resolution to be valid. This preserves the AnimationJoint's pointer
# to RenderAnimation (non-null) so the re-parser knows it exists, even though
# the animation data itself is lost.
#
# TODO: Define proper fields based on HSDLib's RObjAnim struct to enable
# full round-trip of render animation data.
class RenderAnimation(Node):
    class_name = "Render Animation"
    fields = []

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        # Determine struct size by scanning for the last relocation within range
        max_extent = 0
        for reloc_addr in parser.relocation_table:
            offset = reloc_addr - self.address
            if 0 <= offset < 256:
                max_extent = max(max_extent, offset + 4)

        if max_extent == 0:
            # No relocations — check for non-zero data up to 52 bytes
            raw = parser.read_chunk(52, self.address, parser._startOffset(True))
            for i in range(len(raw) - 1, -1, -1):
                if raw[i] != 0:
                    max_extent = ((i + 4) // 4) * 4
                    break

        self._raw_size = max(max_extent, 8)  # minimum 8 bytes for a valid stub

    def allocationSize(self):
        return getattr(self, '_raw_size', 8)
