from ..Node import Node

# Pixel Engine (aka PE)
class PixelEngine(Node):
    class_name = "Pixel Engine"
    fields = [
        ('flags', 'uchar'),
        ('reference_0', 'uchar'),
        ('reference_1', 'uchar'),
        ('dst_alpha', 'uchar'),
        ('type', 'uchar'),
        ('source_factor', 'uchar'),
        ('dst_factor', 'uchar'),
        ('logic_op', 'uchar'),
        ('z_comp', 'uchar'),
        ('alpha_component_0', 'uchar'),
        ('alpha_op', 'uchar'),
        ('alpha_component_1', 'uchar'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass