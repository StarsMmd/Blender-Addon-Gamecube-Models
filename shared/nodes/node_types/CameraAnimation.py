from ..Node import Node

# Camera Animation
class CameraAnimation(Node):
    class_name = "Camera Animation"
    fields = [
        ('animation', 'Animation'),
        ('eye_position_animation', 'WObject'),
        ('interest_animation', 'WObject'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass