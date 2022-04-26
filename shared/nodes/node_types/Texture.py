from ..Node import Node

# Texture (aka TObject)
class Texture(Node):
    class_name = "Texture"
    fields = [
        ('class_type', 'string'),
        ('next', 'Texture'),
        ('texture_id', 'uint'),
        ('source', 'uint'),
        ('rotation', 'vec3'),
        ('scale', 'vec3'),
        ('translation', 'vec3'),
        ('wrap_s', 'uint'),
        ('wrap_t', 'uint'),
        ('repeat_s', 'uchar'),
        ('repeat_t', 'uchar'),
        ('flag', 'uint'),
        ('blending', 'float'),
        ('mag_filter', 'uint'),
        ('image', 'Image'),
        ('tlut', 'Tlut'),
        ('lod', 'TextureLOD'),
        ('tev', 'TextureTEV'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass