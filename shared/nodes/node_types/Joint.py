from ..Node import Node
from ...hsd import JOBJ_PARTICLE
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
        ('robject', 'RObject')
    ]

    # Parse struct from binary file.
    @classmethod
    def fromBinary(cls, parser, address):
        flags = parser.read('uint', address + 4)

        property_type = 'Mesh'

        if flags & JOBJ_PARTICLE:
            property_type = 'Particle'
        elif flags & JOBJ_SPLINE:
            property_type = 'Spline'

        fields = [
            ('name', 'string'),
            ('flags', 'uint'),
            ('child', 'Joint'),
            ('next', 'Joint'),
            ('property', property_type),
            ('rotation', 'vec3'),
            ('scale', 'vec3'),
            ('position', 'vec3'),
            ('inverse_bind', 'matrix'),
            ('robject', 'RObject')
        ]

        return parser.parseStruct(cls, address, fields)

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        return builder.writeStruct(self)

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass