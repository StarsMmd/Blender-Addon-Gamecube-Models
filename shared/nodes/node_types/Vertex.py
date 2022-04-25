from ..Node import Node

# Vertex
class Vertex(Node):
    class_name = "Vertex"
    fields = [
        ('attribute', 'uint'),
        ('attribute_type', 'uint'),
        ('component_count', 'uint'),
        ('component_type', 'uint'),
        ('component_frac', 'uchar'),
        ('stride', 'ushort'),
        ('base_pointer', 'uint'),
    ]

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