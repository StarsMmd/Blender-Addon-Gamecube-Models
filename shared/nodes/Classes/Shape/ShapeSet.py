from ...Node import Node
from ....Errors import *

# Shape Set
class ShapeSet(Node):
    class_name = "Shape Set"
    fields = [
        ('flags', 'ushort'),
        ('shape_count', 'ushort'),
        ('vertex_tri_count', 'uint'),
        ('vertices', 'VertexList'),
        ('vertex_set', '*((*((@ShapeIndexTri)[vertex_tri_count]))[shape_count])'),
        ('normal_tri_count', 'uint'),
        ('normals', 'VertexList'),
        ('normal_set', '*((*((@ShapeIndexTri)[normal_tri_count]))[shape_count])'),
    ]

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        # TODO: set vt count, nt count, shape count based on dimension of vertex_set and normal_set
        if len(vertex_set) != len(normal_set):
            raise ShapeSetDimensionMismatchError

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
