from ..Node import Node

# Shape Index Tri
class ShapeIndexTri(Node):
    class_name = "Shape Index Tri"
    fields = [
        ('id0', 'uchar'),
        ('id1', 'uchar'),
        ('id2', 'uchar')
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass