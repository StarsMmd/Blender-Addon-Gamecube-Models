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
    @classmethod
    def fromBinary(cls, parser, address):
        shape_count = parser.read('ushort', address + 2)
        vertex_index_count = parser.read('uint', address + 4)
        normal_index_count = parser.read('uint', address + 16)
        shape_vertices_type = "(@ShapeIndexTri)[{vi_count}]".format(
            vi_count = vertex_index_count
        )
        vertex_set_type = '*((*{shape})[{s_count}])'.format(
            shape = shape_vertices_type,
            s_count = shape_count
        )

        shape_normal_type = "(@ShapeIndexTri)[{ni_count}]".format(
            ni_count = normal_index_count
        )
        normal_set_type = '*((*{shape})[{s_count}])'.format(
            shape = shape_nromal_type,
            s_count = shape_count
        )

        fields = [
            ('flags', 'ushort'),
            ('shape_count', 'ushort'),
            ('vertex_index_count', 'uint'),
            ('vertices', 'Vertex[]'),
            ('vertex_set', vertex_set_type),
            ('normal_index_count', 'uint'),
            ('normal', 'Vertex[]'),
            ('normal_set', normal_set_type)
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