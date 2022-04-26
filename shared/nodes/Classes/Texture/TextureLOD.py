from ...Node import Node

# Texture LOD
class TextureLOD(Node):
    class_name = "Texture LOD"
    fields = [
        ('min_filter', 'uint'),
        ('LOD_bias', 'float'),
        ('bias_clamp', 'uchar'),
        ('enable_edge_LOD', 'uchar'),
        ('max_aniso', 'uint'),
    ]
