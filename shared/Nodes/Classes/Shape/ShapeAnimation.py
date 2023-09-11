from ...Node import Node

# Shape Animation
class ShapeAnimation(Node):
    class_name = "ShapeAnimation"
    fields = [
        ('next', 'ShapeAnimation'),
        ('animation', 'Animation'),
    ]

