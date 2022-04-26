from ..Node import Node

# Camera
class Camera(Node):
    class_name = "Camera"
    fields = [
        ('name', 'string'),
        ('flags', 'ushort'),
        ('perspective_flags', 'ushort'),
        ('viewport', 'ushort[4]'),
        ('scissor', 'ushort[4]'),
        ('position', 'WObject'),
        ('interest', 'WObject'),
        ('roll', 'float'),
        ('up_vector', '*vec3'),
        ('near', 'float'),
        ('far', 'float'),
        ('field_of_view', 'float'),
        ('aspect', 'float'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass