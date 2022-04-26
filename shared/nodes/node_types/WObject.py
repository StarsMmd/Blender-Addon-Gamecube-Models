from ..Node import Node

# W Object
class WObject(Node):
    class_name = "W Object"
    fields = [
        ('name', 'string'),
        ('position', 'vec3'),
        ('render', 'Render'),
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass