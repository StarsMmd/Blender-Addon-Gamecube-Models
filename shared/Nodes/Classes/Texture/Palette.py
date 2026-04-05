from ...Node import Node
from ....Constants import *
from .Image import *

# Palette (aka Texture Lookup Table, aka TLUT)
class Palette(Node):
    class_name = "Palette"
    fields = [
        ('data', 'uint'),
        ('format', 'uint'),
        ('table_name', 'string'),
        ('entry_count', 'ushort'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        # If the lookup table gets set to a proper value rather than just the pointer
        # then make sure the id is still the address of the table
        self.id = self.data

        if self.format not in palette_format_dict:
            parser.logger.warning("Palette 0x%X: unknown format %d", self.address, self.format)
            self.raw_data = b''
            return

        bits_per_pixel, _ = palette_format_dict[self.format]
        bytes_per_color = bits_per_pixel // 8
        data_size = self.entry_count * bytes_per_color

        parser.logger.debug("Palette 0x%X: format=%d, entries=%d, data_size=%d bytes",
                            self.address, self.format, self.entry_count, data_size)

        # Read palette as raw bytes — the image converter's get_palette_color()
        # decodes colors directly from byte data
        self.raw_data = parser.read_chunk(data_size, self.data, parser._startOffset(True))

    def writePrimitivePointers(self, builder):
        """Write shared palette data (Phase 1)."""
        if not hasattr(self, '_raw_pointer_fields'):
            self._raw_pointer_fields = set()
        if hasattr(self, 'raw_data') and self.raw_data:
            builder.seek(0, 'end')
            builder.align_buffer()
            self.data = builder._currentRelativeAddress()
            for byte in self.raw_data:
                builder.write(byte, 'uchar')
            self._raw_pointer_fields.add('data')
        else:
            self.data = 0

palette_format_dict = {
    #                 bits per pixel | type
    0:    (BITSPPX_IA8   ,  'IA8Color'   ),
    1:    (BITSPPX_RGB565,  'RGB565Color'),
    2:    (BITSPPX_RGB5A3,  'RGB5A3Color'),
}