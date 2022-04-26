from ..Node import Node

# Spline
class Spline(Node):
    class_name = "Spline"
    fields = [
        ('flags', 'ushort'),
        ('n', 'ushort'),
        ('f0', 'float'),
        ('s1', 'uint'),
        ('f1', 'float'),
        ('s2', 'uint'),
        ('s3', 'uint'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        # TODO: complete spline implememtation

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass