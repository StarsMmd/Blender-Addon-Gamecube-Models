from ...Node import Node
from .Color import Color

# RGBA Color (aka RGBA8 Color)
# TODO: Confirm if these need to be aligned by a 4 byte boundary.
# If so then read the fields as a single 32bit raw value and parse the color components in
# loadFromBinary.
class RGBAColor(Node, Color):
    class_name = "RGBA8 Color"
    is_cachable = False
    fields = [
        ('red', 'uchar'),
        ('green', 'uchar'),
        ('blue', 'uchar'),
        ('alpha', 'uchar'),
    ]

class RGB565Color(Node, Color):
    class_name = "RGB565 Color"
    is_cachable = False
    fields = [
        ('raw_value', 'ushort')
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        self.blue = (self.raw_value % 0x20) << 3
        self.green = ((self.raw_value >> 5) % 0x40) << 2
        self.red = (self.raw_value >> 11) << 3
        self.alpha = 0xFF

    def writeBinary(self, builder):
        self.raw_value = 0  
        self.raw_value += (self.red >> 3) << 11
        self.raw_value += (self.green >> 2) << 5
        self.raw_value += (self.blue >> 3)

        super().writeBinary(builder)

class RGB8Color(Node, Color):
    class_name = "RGB8 Color"
    is_cachable = False
    fields = [
        ('red', 'uchar'),
        ('green', 'uchar'),
        ('blue', 'uchar')
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        self.alpha = 0xFF

# TODO: Confirm if these need to be aligned by a 4 byte boundary.
# If so then read the fields as a single 32bit raw value and parse the color components in
# loadFromBinary.
class RGBX8Color(Node, Color):
    class_name = "RGBX8 Color"
    is_cachable = False
    fields = [
        ('red', 'uchar'),
        ('green', 'uchar'),
        ('blue', 'uchar'),
        ('padding', 'uchar')
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        self.alpha = 0xFF

    def writeBinary(self, builder):
        self.padding = 0
        super().writeBinary(builder)

class RGBA4Color(Node, Color):
    class_name = "RGBA4 Color"
    is_cachable = False
    fields = [
        ('raw_value', 'ushort')
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        self.red = (self.raw_value >> 12) << 4
        self.green = ((self.raw_value >> 8) & 0xF) << 4
        self.blue = ((self.raw_value >> 4) & 0xF) << 4
        self.alpha = (self.raw_value & 0xF) << 4

    def writeBinary(self, builder):
        self.raw_value = 0
        self.raw_value += (self.red >> 4) << 12
        self.raw_value += (self.green >> 4) << 8
        self.raw_value += (self.blue >> 4) << 4
        self.raw_value += (self.alpha >> 4)

        super().writeBinary(builder)

class RGBA6Color(Node, Color):
    class_name = "RGBA6 Color"
    is_cachable = False
    fields = [
        ('raw_bytes', 'uchar[3]')
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        raw_value = (raw_bytes[0] << 16) + (raw_bytes[1] << 8) + raw_bytes[2]
        self.red = (self.raw_value >> 18) << 2
        self.green = ((self.raw_value >> 12) & 0x3F) << 2
        self.blue = ((self.raw_value >> 6) & 0x3F) << 2
        self.alpha = (self.raw_value & 0x3F) << 2

    def writeBinary(self, builder):
        self.raw_value = 0
        self.raw_value += (self.red >> 2) << 18
        self.raw_value += (self.green >> 2) << 12
        self.raw_value += (self.blue >> 2) << 6
        self.raw_value += (self.alpha >> 2)
        super().writeBinary(builder)








