from ..Node import Node

# Attn
class Attn(Node):
    class_name = "Attn"
    fields = [
        ('angle', 'vec3'),
        ('distance', 'vec3'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass