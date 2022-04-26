from ..Node import Node

# Material Object
class MaterialObject(Node):
    class_name = "Material Object"
    fields = [
        ('class_type', 'string'),
        ('render_mode', 'uint'),
        ('texture', 'Texture'),
        ('material', 'Material'),
        ('render_data', 'Render'),
        ('pe_data', 'PixelEngine'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass