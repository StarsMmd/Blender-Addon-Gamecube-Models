from ...Node import Node
from ....Constants import *

# Light
class Light(Node):
    class_name = "Light"
    fields = [
        ('name', 'string'),
        ('link', 'Light'),
        ('flags', 'ushort'),
        ('attn_flags', 'ushort'),
        ('color', '@RGBAColor'),
        ('position', 'WObject'),
        ('interest', 'WObject'),
        ('property', 'uint'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        if self.attn_flags & LOBJ_LIGHT_ATTN:
            self.property = parser.read('Attn', self.property)
        else:
            if self.flags == LOBJ_INFINITE:
                self.property = parser.read('float', self.property)
            elif self.flags == LOBJ_POINT:
                self.property = parser.read('PointLight', self.property)
            elif self.flags == LOBJ_SPOT:
                self.property = parser.read('SpotLight', self.property)
            else: # LOBJ_AMBIENT
                self.property = None

    def writeBinary(self, builder):
        if isinstance(self.property, Attn):
            self.flags = 0
            self.attn_flags = LOBJ_LIGHT_ATTN
            self.property = self.property.address

        elif isinstance(self.property, float):
            self.flags = LOBJ_INFINITE
            self.attn_flags = 0
            self.property = self.property.address

        elif isinstance(self.property, PointLight):
            self.flags = LOBJ_POINT
            self.attn_flags = 0
            self.property = self.property.address

        elif isinstance(self.property, SpotLight):
            self.flags = LOBJ_SPOT
            self.attn_flags = 0
            self.property = self.property.address

        else:
            self.flags = 0
            self.attn_flags = 0
            self.property = 0

        super().writeBinary(builder)

