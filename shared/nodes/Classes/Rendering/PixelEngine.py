from ...Node import Node

# Pixel Engine (aka PE)
class PixelEngine(Node):
    class_name = "Pixel Engine"
    fields = [
        ('flags', 'uchar'),
        ('reference_0', 'uchar'),
        ('reference_1', 'uchar'),
        ('destination_alpha', 'uchar'),
        ('type', 'uchar'),
        ('source_factor', 'uchar'),
        ('destination_factor', 'uchar'),
        ('logic_op', 'uchar'),
        ('z_comp', 'uchar'),
        ('alpha_component_0', 'uchar'),
        ('alpha_op', 'uchar'),
        ('alpha_component_1', 'uchar'),
    ]
