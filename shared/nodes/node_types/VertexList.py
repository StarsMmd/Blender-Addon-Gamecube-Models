from ..Node import Node

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
        vertex_length = parser.getTypeLength('Vertex')

        found_end_of_list = False
        while not found_end_of_list:
            vertex = parser.read('Vertex', self.address, current_offset)
            self.vertices.append(vertex)
            if vertex.attribute == 0xFF:
                found_end_of_list = True
            current_offset += vertex_length

    # For any fields which are a pointer where the underlying sub type is a primitive type,
    # write them to the builder's output and replace the field with the address it was written to
    def writePrimitivePointers(self, builder):
        for vertex in self.vertices:
            vertex.writePrimitivePointers(builder)

    # Tells the builder how many bytes to reserve for this node.
    def allocationSize(self):
        vertex_length = parser.getTypeLength('Vertex')
        return vertex_length * len(self.vertices)

    # Tells the builder how to write this node's data to the binary file.
    # The node should have had its write address allocated by the builder by the time this is called.
    def writeBinary(self, builder):
        vertex_length = parser.getTypeLength('Vertex')
        for (i, vertex) in enumerate(self.vertices):
            vertex.address = self.address + (i * vertex_length)
            vertex.writeBinary(builder)
        

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        #Override this in sub classes
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        #Override this in sub classes
        pass

    # Treat this as one complete node so the vertex nodes are always written in the correct order
    # and with custom logic for the terminator.
    def toList(self):
        return [self]
