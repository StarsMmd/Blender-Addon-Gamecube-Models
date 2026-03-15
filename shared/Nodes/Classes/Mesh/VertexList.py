from ...Node import Node
from ....Errors import *

# Vertex List
class VertexList(Node):
    class_name = "Vertex List"
    fields = [
        ('vertices', '(@Vertex)[]'),
    ]

    # Parse struct from binary file.
    def loadFromBinary(self, parser):
        self.vertices = []
        current_offset = 0
        self.vertex_length = parser.getTypeLength('Vertex')

        found_end_of_list = False
        while not found_end_of_list:
            vertex = parser.read('Vertex', self.address, current_offset)
            if vertex.attribute == 0xFF:
                found_end_of_list = True
            else:
                self.vertices.append(vertex)
                current_offset += self.vertex_length

    # For any fields which are a pointer where the underlying sub type is a primitive type,
    # write them to the builder's output and replace the field with the address it was written to
    def writePrimitivePointers(self, builder):
        for vertex in self.vertices:
            vertex.writePrimitivePointers(builder)

    # Tells the builder how many bytes to reserve for this node.
    def allocationSize(self):
        # +1 for the 0xFF terminator vertex
        return self.vertex_length * (len(self.vertices) + 1)

    # Tells the builder how to write this node's data to the binary file.
    # The node should have had its write address allocated by the builder by the time this is called.
    def writeBinary(self, builder):
        for (i, vertex) in enumerate(self.vertices):
            vertex.address = self.address + (i * self.vertex_length)
            vertex.writeBinary(builder)

        # Write terminator vertex (attribute = 0xFF, rest zeroed)
        terminator_address = self.address + (len(self.vertices) * self.vertex_length)
        abs_address = terminator_address + builder.DAT_header_length
        builder.seek(abs_address)
        builder.file.write(b'\x00' * self.vertex_length)
        builder.write(0xFF, 'uint', terminator_address, relative_to_header=True)
        

    # Treat this as one complete node so the vertex nodes are always written in the correct order
    # and with custom logic for the terminator.
    def toList(self):
        return [self]
