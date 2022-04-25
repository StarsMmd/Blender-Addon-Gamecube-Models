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
        ('vertex_list', 'VertexList'),
        ('flags', 'ushort'),
        ('display_list_chunk_count', 'ushort'),
        ('display_list', 'uint'),
        ('property', 'uint')
    ]

    # Parse struct from binary file.
    def loadFromBinary(self, parser):
        parser.parseNode(self)

        display_list_length = self.display_list_chunk_count * 32
        display_list_type = 'uchar[{count}]'.format(
            count = display_list_length
        )
        self.display_list = parser.read(display_list_type, self.display_list)

        if self.property > 0:
            property_type = self.flags & POBJ_TYPE_MASK
            if property_type == POBJ_SKIN:
                self.property = parser.read('Joint', self.property)
            elif property_type == POBJ_SHAPEANIM:
                self.property = parser.read('ShapeSet', self.property)
            else:
                self.property = parser.read('(*Envelope)[]', self.property)
        else:
            self.property = None

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