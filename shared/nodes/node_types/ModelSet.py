from ..Node import Node

# Model Set
class ModelSet(Node):
    class_name = "Model Set"
    fields = [
        ('joint', 'Joint'),
        ('animated_joint', 'AnimatedJoint'),
        ('animated_material_joint', 'AnimatedMaterialJoint'),
        ('animated_shape_joint', 'AnimatedShapeJoint')
    ]

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass






