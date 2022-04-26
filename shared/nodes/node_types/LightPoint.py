from ..Node import Node

# Light Point
class LightPoint(Node):
    class_name = "Light Point"
    fields = [
        ('reference_br', 'float'),
        ('reference_distance', 'float'),
        # TODO: confirm if there's a third field here or not
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass