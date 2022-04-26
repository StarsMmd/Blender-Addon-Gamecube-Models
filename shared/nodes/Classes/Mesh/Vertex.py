from ...Node import Node

# Vertex
class Vertex(Node):
    class_name = "Vertex"
    is_cachable = False
    fields = [
        ('attribute', 'uint'),
        ('attribute_type', 'uint'),
        ('component_count', 'uint'),
        ('component_type', 'uint'),
        ('component_frac', 'uchar'),
        ('stride', 'ushort'),
        ('base_pointer', 'uint'),
    ]
