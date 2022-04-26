from ..Node import Node

# Animation
class Animation(Node):
    class_name = "Animation"
    fields = [
        ('flags', 'uint'),
        ('end_frame', 'float'),
        ('frame', 'Frame'),
        ('joint', 'Joint'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass