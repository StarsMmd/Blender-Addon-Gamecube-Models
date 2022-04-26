from ...Node import Node
from ....Constants import *

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

        bits_per_color = 32 if self.format == gx.GX_TF_RGBA8 else 16
        palette_size = entry_count * bits_per_color
        self.data = parser.read_chunk(palette_size, self.data)

