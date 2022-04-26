from ..Node import Node

# Material
class Material(Node):
    class_name = "Material"
    fields = [
        ('ambient', '@RGBAColor'),
        ('diffuse', '@RGBAColor'),
        ('specular', '@RGBAColor'),
        ('alpha', 'float'),
        ('shininess', 'float'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass