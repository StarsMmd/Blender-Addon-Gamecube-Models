from ..Node import Node

# Viewport
class Viewport(Node):
    class_name = "Viewport"
    fields = [
        ('ix', 'ushort'),
        ('iw', 'ushort'),
        ('iy', 'ushort'),
        ('ih', 'ushort'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass