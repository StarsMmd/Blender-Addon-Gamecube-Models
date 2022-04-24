from ..Node import Node

# Shape Set
class ShapeSet(Node):
    class_name = "Shape Set"
    fields = [
        ('flags', 'ushort'),
        ('shape_count', 'ushort'),
        ('vertex_tri_count', 'uint'),
        ('vertices', 'Vertex[]'),
        ('vertex_set', 'uint'),
        ('normal_tri_count', 'uint'),
        ('normal', 'Vertex[]'),
        ('normal_set', 'uint'),
    ]

    # Parse struct from binary file.
    def loadFromBinary(self, parser):
        parser.parseNode(self)

        shape_vertices_type = "(@ShapeIndexTri)[{vi_count}]".format(
            vi_count = self.vertex_index_count
        )
        vertex_set_type = '*((*{shape})[{s_count}])'.format(
            shape = shape_vertices_type,
            s_count = self.shape_count
        )
        self.vertex_set = parser.read(vertex_set_type, self.vertex_set)

        shape_normal_type = "(@ShapeIndexTri)[{ni_count}]".format(
            ni_count = self.normal_index_count
        )
        normal_set_type = '*((*{shape})[{s_count}])'.format(
            shape = shape_normal_type,
            s_count = self.shape_count
        )
        self.normal_set = parser.read(normal_set_type, self.normal_set)

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