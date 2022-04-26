from ...Node import Node

# Texture TEV
class TextureTEV(Node):
    class_name = "Texture TEV"
    fields = [
        ('color_op', 'uchar'),
        ('alpha_op', 'uchar'),
        ('color_bias', 'uchar'),
        ('alpha_bias', 'uchar'),
        ('color_scale', 'uchar'),
        ('alpha_scale', 'uchar'),
        ('color_clamp', 'uchar'),
        ('alpha_clamp', 'uchar'),
        ('color_a', 'uchar'),
        ('color_b', 'uchar'),
        ('color_c', 'uchar'),
        ('color_d', 'uchar'),
        ('alpha_a', 'uchar'),
        ('alpha_b', 'uchar'),
        ('alpha_c', 'uchar'),
        ('alpha_d', 'uchar'),
        ('constant', 'uchar[4]'),
        ('tev0', 'uchar[4]'),
        ('tev1', 'uchar[4]'),
        ('active', 'uint'),
    ]
