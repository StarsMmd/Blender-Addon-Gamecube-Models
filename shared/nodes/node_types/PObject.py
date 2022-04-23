from ..Node import Node
from ...hsd import POBJ_TYPE_MASK
from ...hsd import POBJ_SKIN
from ...hsd import POBJ_SHAPEANIM

# PObject
class PObject(Node):
    class_name = "P Object"
    fields = [
        ('name', 'string'),
        ('next', 'PObject'),
        ('vertex_list', 'Vertex[]'),
        ('flags', 'ushort'),
        ('disp_list_count', 'ushort'),
        ('disp_list', 'uint'),
        ('property', 'uint')
    ]

    # Parse struct from binary file.
    @classmethod
    def fromBinary(cls, parser, address):
        disp_list_count = parser.read('ushort', address + 14)
        disp_list_type = 'uint[{count}]'.format(
            count = disp_list_count
        )

        flags = parser.read('uint', address + 12)
        property_type = flags & POBJ_TYPE_MASK
        property_type_string = 'Envelope[]'
        if property_type == POBJ_SKIN:
            property_type_string = 'Joint'
        if property_type == POBJ_SHAPEANIM:
            property_type = 'ShapeSet'

        fields = [
            ('name', 'string'),
            ('next', 'PObject'),
            ('vertex_list', 'Vertex[]'),
            ('flags', 'ushort'),
            ('disp_list_count', 'ushort'),
            ('disp_list', disp_list_type), 
            ('property', property_type_string)
        ]
        return parser.parseStruct(cls, address, fields)

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        self.disp_list_count = disp_list.length
        return builder.writeStruct(self)

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass