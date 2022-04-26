from ...Node import Node
from ....Constants import *
from ..Joints import *
from ..Shape import *

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
        super().loadFromBinary(parser)

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

    def allocationSize(self):
        # If the property is an Envelope list then allocate space for
        # the list of pointers.
        size = super().allocationSize()
        if isinstance(self.property, list):
            size += len(self.property) * 4
        return size

    def allocationOffset(self):
        offset = super().allocationOffset()
        if isinstance(self.property, list):
            offset += len(self.property) * 4
        return offset

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        self.disp_list_count = disp_list.length
        if isinstance(self.property, Joint):
            self.flags = POBJ_SKIN
            self.property = self.property.address

        elif isinstance(self.property, ShapeSet):
            self.flags = POBJ_SHAPEANIM
            self.property = self.property.address
            
        else:
            self.flags = 0

        super().writeBinary(builder)
