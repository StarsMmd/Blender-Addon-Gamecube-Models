from ..Node import Node

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

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass