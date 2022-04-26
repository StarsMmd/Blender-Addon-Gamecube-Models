from ...Node import Node

# Material Animation Joint
class MaterialAnimationJoint(Node):
    class_name = "Material Animation Joint"
    fields = [
        ('child', 'MaterialAnimationJoint'),
        ('next', 'MaterialAnimationJoint'),
        ('animation', 'MaterialAnimation'),
    ]

