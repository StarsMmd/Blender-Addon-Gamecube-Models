from ...Node import Node
from .Joint import Joint

# Reference (aka RObject)
class Reference(Node):
    class_name = "Reference"
    fields = [
        ('next', 'Reference'),
        ('flags', 'uint'),
        ('property', 'uint'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        if (self.flags & 0x70000000 == 0x10000000):
            self.property = parser.read('Joint', self.property)
        elif (self.flags & 0x70000000 == 0x40000000):
            self.property = parser.read('float[2]', self.property)

    def writeBinary(self, builder):
        if self.property == None:
            self.flags = 0

        elif isinstance(self.property, Joint):
            self.flags = 0x10000000

        elif isinstance(self.property, list):
            self.flags = 0x40000000

        else:
            self.flags = 0

        super().writeBinary(builder)