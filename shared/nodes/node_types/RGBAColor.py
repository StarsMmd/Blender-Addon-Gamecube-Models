from ..Node import Node

# RGBA Color (aka GBAColor)
class RGBAColor(Node):
    class_name = "RGBA Color"
    is_sub_struct = True
    fields = [
        ('red', 'uchar'),
        ('green', 'uchar'),
        ('blue', 'uchar'),
        ('alpha', 'uchar'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass