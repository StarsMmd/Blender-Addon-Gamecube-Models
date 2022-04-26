from ..Node import Node

# Render
class Render(Node):
    class_name = "Render"
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