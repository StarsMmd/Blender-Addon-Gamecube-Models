from ..Node import Node

# S List
class SList(Node):
    class_name = "S List"
    fields = [
        ('next', 'SList'),
        ('data', 'uint'), # TODO: confirm what kind of data this points to
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass