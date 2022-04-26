from ..Node import Node

# Shape Animation Joint
class ShapeAnimationJoint(Node):
    class_name = "Shape Animation Joint"
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