from ..Node import Node

# Fog Adj
class FogAdj(Node):
    class_name = "Fog Adj"
    fields = []

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass