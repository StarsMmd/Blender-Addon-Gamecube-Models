from ...Node import Node

# Bone Reference
class BoneReference(Node):
    class_name = "Bone Reference"
    fields = [
        ('length', 'float'),
        ('pole_angle', 'float'),
    ]