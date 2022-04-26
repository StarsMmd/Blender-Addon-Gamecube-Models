from ..Node import Node

# Image
class Image(Node):
    class_name = "Image"
    fields = [
        ('image_data', 'uint'),
        ('width', 'ushort'),
        ('height', 'ushort'),
        ('format', 'uint'),
        ('mipmap', 'uint'),
        ('minLOD', 'float'),
        ('maxLOD', 'float'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass