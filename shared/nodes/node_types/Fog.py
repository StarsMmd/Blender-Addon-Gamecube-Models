from ..Node import Node

# Fog
class Fog(Node):
    class_name = "Fog"
    fields = [
        ('type', 'uint'),
        ('adj', 'FogAdj'),
        ('start_z', 'float'),
        ('end_z', 'float'),
        ('color', '@RGBAColor'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass