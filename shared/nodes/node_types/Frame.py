from ..Node import Node

# Frame (aka FObject)
class Frame(Node):
    class_name = "Key Frame"
    fields = [
        ('next', 'Frame'),
        ('length', 'uint'),
        ('start_frame', 'float'),
        ('type', 'uchar'),
        ('frac_value', 'uchar'),
        ('frac_slope', 'uchar'),
        ('ad', 'uint'), # TODO: confirm what kind of data this points to
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass