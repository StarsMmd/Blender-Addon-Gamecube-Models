from ...Node import Node

# Spot Light
class SpotLight(Node):
    class_name = "Spot Light"
    fields = [
        ('cutoff', 'float'),
        ('spot_flags', 'uint'),
        ('reference_br', 'float'),
        ('reference_distance', 'float'),
        ('distance_attn_flags', 'uint'),
    ]
