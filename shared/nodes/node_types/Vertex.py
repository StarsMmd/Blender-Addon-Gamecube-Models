from ..Node import Node

# Vertex
class Vertex(Node):
    class_name = "Vertex"
    is_sub_struct = True
    fields = [
        ('attribute', 'uint'),
        ('attribute_type', 'uint'),
        ('component_count', 'uint'),
        ('component_type', 'uint'),
        ('component_frac', 'uchar'),
        ('stride', 'ushort'),
        ('base_pointer', 'uint'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass