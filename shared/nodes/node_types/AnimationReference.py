from ..Node import Node

# Animation Reference (aka RObject Animation)
class AnimationReference(Node):
    class_name = "Animation Reference"
    fields = []

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass