from ..Node import Node

# Texture Lookup Table
class Tlut(Node):
    class_name = "Texture Look Up Table"
    fields = [
        ('', ''),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass