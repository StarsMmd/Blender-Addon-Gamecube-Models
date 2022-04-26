from ...Node import Node

# Attn
class Attn(Node):
    class_name = "Attn"
    fields = [
        ('angle', 'vec3'),
        ('distance', 'vec3'),
    ]
