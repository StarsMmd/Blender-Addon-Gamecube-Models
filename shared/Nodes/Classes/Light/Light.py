from ...Node import Node
from ....Constants import *
from . import Attn, PointLight, SpotLight

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

        light_type = self.flags & LOBJ_TYPE_MASK

        if self.attn_flags & LOBJ_LIGHT_ATTN:
            parser.logger.debug("Light 0x%X: property -> Attn at 0x%X", self.address, self.property)
            self.property = parser.read('Attn', self.property)
        else:
            if light_type == LOBJ_INFINITE:
                parser.logger.debug("Light 0x%X: INFINITE, property -> float at 0x%X", self.address, self.property)
                self.property = parser.read('float', self.property)
            elif light_type == LOBJ_POINT:
                parser.logger.debug("Light 0x%X: POINT, property -> PointLight at 0x%X", self.address, self.property)
                self.property = parser.read('PointLight', self.property)
            elif light_type == LOBJ_SPOT:
                parser.logger.debug("Light 0x%X: SPOT, property -> SpotLight at 0x%X", self.address, self.property)
                self.property = parser.read('SpotLight', self.property)
            else: # LOBJ_AMBIENT
                parser.logger.debug("Light 0x%X: AMBIENT, no property", self.address)
                self.property = None

    def writePrivateData(self, builder):
        super().writePrivateData(builder)
        # For INFINITE lights, property is a float that needs to be written as raw data
        if isinstance(self.property, float):
            builder.seek(0, 'end')
            self.property = builder.write(self.property, 'float')
            self._raw_pointer_fields.add('property')

    def writeBinary(self, builder):
        # For node-reference cases: an `address is not None` means the
        # node was actually allocated. address == 0 is a legitimate
        # allocation (start of data section) and still needs its
        # relocation recorded — discriminate on `is not None`, not
        # `!= 0`, so single-light or no-vertex models don't silently
        # drop these relocs when a referenced struct lands at offset 0.
        if isinstance(self.property, Attn):
            referenced = self.property.address is not None
            self.property = self.property.address if referenced else 0
            if referenced:
                self._raw_pointer_fields.add('property')

        elif isinstance(self.property, PointLight.PointLight):
            referenced = self.property.address is not None
            self.property = self.property.address if referenced else 0
            if referenced:
                self._raw_pointer_fields.add('property')

        elif isinstance(self.property, SpotLight.SpotLight):
            referenced = self.property.address is not None
            self.property = self.property.address if referenced else 0
            if referenced:
                self._raw_pointer_fields.add('property')

        elif self.property is None:
            self.property = 0

        # else: property is already an int address (from writePrimitivePointers for floats)

        super().writeBinary(builder)

