from ..Node import Node

# Light Set
class LightSet(Node):
    class_name = "Light Set"
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