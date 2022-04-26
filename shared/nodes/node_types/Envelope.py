from ..Node import Node

# Envelope
class Envelope(Node):
    class_name = "Envelope"
    fields = [
        ('joint', 'Joint'),
        ('weight', 'float'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass