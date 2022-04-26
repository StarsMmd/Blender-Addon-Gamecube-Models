from ..Node import Node

# W Object Animation
class WObjectAnimation(Node):
    class_name = "W Object Animation"
    fields = [
        ('animation', 'Animation'),
        ('render_animation', 'RenderAnimation'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass