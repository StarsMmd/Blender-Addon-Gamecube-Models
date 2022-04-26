from ..Node import Node

# Material Animation
class MaterialAnimation(Node):
    class_name = "Material Animation"
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