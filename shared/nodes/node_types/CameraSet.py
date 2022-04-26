from ..Node import Node

# Camera Set
class CameraSet(Node):
    class_name = "Camera Set"
    fields = [
        ('camera', 'Camera'),
        ('camera_animations', 'CameraAnimation[]'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass