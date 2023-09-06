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

        bits_per_pixel, is_indexed, blockWidth, blockHeight, type = format_dict[self.format]
        bits_per_color = 32 if self.format == gx.GX_TF_RGBA8 else 16
        data = []

        for i in range(self.entry_count):
            offset = i * (bits_per_color // 8)
            color = parser.read(type, self.data, offset)
            color.normalize()
            data.append(color)

        self.data = data