from ...Node import Node
from ....Errors import *

# Shape Set
class ShapeSet(Node):
    class_name = "Shape Set"
    fields = [
        ('flags', 'ushort'),
        ('shape_count', 'ushort'),
        ('vertex_tri_count', 'uint'),
        ('vertex', 'Vertex'),
        ('vertex_set', 'uint'),
        ('normal_tri_count', 'uint'),
        ('normal', 'Vertex'),
        ('normal_set', 'uint'),
    ]

    # Parse struct from binary file.
    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        vertex_format = self.vertex.getDirectElementType()
        vertex_format_size = parser.getTypeLength(vertex_format)
        vertex_index_format = self.vertex.getFormat()
        vertex_index_format_size = parser.getTypeLength(vertex_index_format)
        vertex_set_type = '((*((@'+ vertex_index_format + ')[vertex_tri_count]))[shape_count])'
        vertex_set = parser.read(vertex_set_type, self.vertex_set)

        normal_format = self.normal.getDirectElementType()
        normal_format_size = parser.getTypeLength(normal_format)
        normal_index_format = self.normal.getFormat()
        normal_index_format_size = parser.getTypeLength(normal_index_format)
        normal_set_type = '((*((@'+ normal_index_format + ')[normal_tri_count]))[shape_count])'
        self.normal_set = parser.read(normal_set_type, self.normal_set)

        self.vertex_set = []
        for shape_index in range(self.shape_count + 1):
            vertex_list = []

            for tri_index in range(self.vertex_tri_count):
                #Dunno if this works for meshes with normalized vertex indices
                index = vertex_set[shape_index][tri_index]
                position = self.vertex.stride * index
                value = parser.read(vertex_format, self.vertex.base_pointer, position)
                vertex_list.append(value)

            self.vertex_set.append(vertex_list)

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        # TODO: set vt count, nt count, shape count based on dimension of vertex_set and normal_set
        if len(vertex_set) != len(normal_set):
            raise ShapeSetDimensionMismatchError(len(vertex_set), len(normal_set))

        if isinstance(vertex_set, list):
            self.shape_count = len(vertex_set)
            if len(vertex_set) == 0:
                self.vertex_tri_count = 0
            elif isinstance(vertex_set[0], list):
                self.vertex_tri_count = len(vertex_set[0])

        if isinstance(normal_set, list):
            if len(normal_set) == 0:
                self.normal_tri_count = 0
            elif isinstance(vertex_set[0], list):
                self.normal_tri_count = len(normal_set[0])

        super().writeBinary(builder)
