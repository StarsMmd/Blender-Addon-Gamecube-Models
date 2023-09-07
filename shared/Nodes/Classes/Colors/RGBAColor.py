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

    def __str__(self):
        return "red: " + str(self.red) + "\ngreen: " + str(self.green) + "\nblue: " + str(self.blue) + "\nalpha: " + str(self.alpha)

class RGB5A3Color(Node, Color):
    class_name = "RGB5A3 Color"
    is_cachable = False
    fields = [
        ('raw_value', 'ushort')
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        top = self.raw_value >> 15
        
        if top == 1:
            current_color = self.raw_value & 0x7FFF
            
            self.blue = (current_color % 0x20) * 8
            
            current_color = current_color >> 5
            self.green = (current_color % 0x20) * 8
            
            current_color = current_color >> 5
            self.red = (current_color % 0x20) * 8
            
            self.alpha = 0xFF
        else:
            current_color = self.raw_value & 0x7FFF
            
            self.blue = (current_color % 0x10) * 0x11
            
            current_color = current_color >> 4
            self.green = (current_color % 0x10) * 0x11
            
            current_color = current_color >> 4
            self.red = (current_color % 0x10) * 0x11
            
            current_color = current_color >> 4
            self.alpha = current_color * 0x20

    def writeBinary(self, builder):
        self.raw_value = 0
        
        if alpha == 0xFF:
            self.raw_value += 1 << 15
            self.raw_value += (self.red / 8)   << 10
            self.raw_value += (self.green / 8) << 5
            self.raw_value += (self.blue / 8)
        else:
            self.raw_value += (self.alpha / 0x20) << 12
            self.raw_value += (self.red / 0x11)   << 8
            self.raw_value += (self.green / 0x11) << 4
            self.raw_value += (self.blue / 0x11)

        super().writeBinary(builder)

    def __str__(self):
        return "red: " + str(self.red) + "\ngreen: " + str(self.green) + "\nblue: " + str(self.blue) + "\nalpha: " + str(self.alpha)

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

    def __str__(self):
        return "red: " + str(self.red) + "\ngreen: " + str(self.green) + "\nblue: " + str(self.blue) + "\nalpha: " + str(self.alpha)

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

    def __str__(self):
        return "red: " + str(self.red) + "\ngreen: " + str(self.green) + "\nblue: " + str(self.blue) + "\nalpha: " + str(self.alpha)

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

    def __str__(self):
        return "red: " + str(self.red) + "\ngreen: " + str(self.green) + "\nblue: " + str(self.blue) + "\nalpha: " + str(self.alpha)

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

    def __str__(self):
        return "red: " + str(self.red) + "\ngreen: " + str(self.green) + "\nblue: " + str(self.blue) + "\nalpha: " + str(self.alpha)

class I8Color(Node, Color):
    class_name = "I8 Color"
    is_cachable = False
    fields = [
        ('intensity', 'uchar')
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        self.red = self.intensity
        self.green = self.intensity
        self.blue = self.intensity
        self.alpha = 0xFF

    def writeBinary(self, builder):
        self.intensity = (self.red + self.green + self.blue) / 3

        super().writeBinary(builder)

    def __str__(self):
        return "red: " + str(self.red) + "\ngreen: " + str(self.green) + "\nblue: " + str(self.blue) + "\nalpha: " + str(self.alpha)

class IA4Color(Node, Color):
    class_name = "IA4 Color"
    is_cachable = False
    fields = [
        ('raw_value', 'uchar')
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        intensity = (self.raw_value & 0xF) << 4

        self.red = intensity
        self.green = intensity
        self.blue = intensity

        self.alpha = self.raw_value & 0xF0

    def writeBinary(self, builder):
        intensity = (((self.red + self.green + self.blue) / 3) >> 4) & 0xF
        alpha = self.alpha & 0xF0
        self.raw_value = alpha + intensity

        super().writeBinary(builder)

    def __str__(self):
        return "red: " + str(self.red) + "\ngreen: " + str(self.green) + "\nblue: " + str(self.blue) + "\nalpha: " + str(self.alpha)

class IA8Color(Node, Color):
    class_name = "IA8 Color"
    is_cachable = False
    fields = [
        ('alpha', 'uchar'),
        ('intensity', 'uchar')
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        self.red = self.intensity
        self.green = self.intensity
        self.blue = self.intensity

    def writeBinary(self, builder):
        self.intensity = (self.red + self.green + self.blue) / 3

        super().writeBinary(builder)

    def __str__(self):
        return "red: " + str(self.red) + "\ngreen: " + str(self.green) + "\nblue: " + str(self.blue) + "\nalpha: " + str(self.alpha)






