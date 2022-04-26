from ..Node import Node
from ...hsd import JOBJ_PTCL
from ...hsd import JOBJ_SPLINE

# Joint
class Joint(Node):
    class_name = "Joint"
    fields = [
        ('name', 'string'),
        ('flags', 'uint'),
        ('child', 'Joint'),
        ('next', 'Joint'),
        ('property', 'uint'),
        ('rotation', 'vec3'),
        ('scale', 'vec3'),
        ('position', 'vec3'),
        ('inverse_bind', 'matrix'),
        ('reference', 'Reference')
    ]

    # Parse struct from binary file.
    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        property_type = 'Mesh'
        if self.flags & JOBJ_PTCL:
            property_type = 'Particle'
        elif self.flags & JOBJ_SPLINE:
            property_type = 'Spline'

        if self.property > 0:
            self.property = parser.read(property_type, self.property)
        else:
            self.property = None

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        if isinstance(self.property, Particle):
            self.flags = JOBJ_PTCL
            self.property = self.property.address

        elif isinstance(self.property, Spline):
            self.flags = JOBJ_SPLINE
            self.property = self.property.address

        else:
            self.flags = 0
            self.property = self.property.address

        super().writeBinary(builder)

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass