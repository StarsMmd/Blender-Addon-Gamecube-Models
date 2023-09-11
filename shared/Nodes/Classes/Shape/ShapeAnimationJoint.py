from ...Node import Node

# Shape Animation Joint
class ShapeAnimationJoint(Node):
    class_name = "Shape Animation Joint"
    fields = [
        ('child', 'ShapeAnimationJoint'),
        ('next', 'ShapeAnimationJoint'),
        ('animation', 'ShapeAnimation'),
    ]

