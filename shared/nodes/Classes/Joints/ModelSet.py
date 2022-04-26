from ...Node import Node

# Model Set
class ModelSet(Node):
    class_name = "Model Set"
    fields = [
        ('joint', 'Joint'),
        ('animated_joints', 'AnimationJoint[]'),
        ('animated_material_joints', 'AnimatedMaterialJoint[]'),
        ('animated_shape_joints', 'AnimatedShapeJoint[]')
    ]

    @classmethod
    def fromRootJoint(cls, joint):
        new_node = ModelSet(0, None)
        new_node.joint = joint
        new_node.animated_joints = []
        new_node.animated_material_joints = []
        new_node.animated_shape_joints = []
        return new_node

