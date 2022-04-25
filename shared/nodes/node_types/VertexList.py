from ..Node import Node

# Vertex List
class VertexList(Node):
    class_name = "Vertex List"

    # Don't cache these. The first node in the list will be read at this address
    # so we need to be able to read this address as a Vertex.
    is_cachable = False

    fields = [
        ('vertices', 'Vertex[]'),
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