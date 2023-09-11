from ...Node import Node

# Shape Animation Mesh
class ShapeAnimationMesh(Node):
    class_name = "Shape Animation Mesh"
    fields = [
        ('next', 'ShapeAnimationMesh'),
        ('animation', 'ShapeAnimation'),
    ]

