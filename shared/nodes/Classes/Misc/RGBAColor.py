from ...Node import Node
from .Color import Color

# RGBA Color
class RGBAColor(Node, Color):
    class_name = "RGBA Color"
    is_cachable = False
    fields = [
        ('red', 'uchar'),
        ('green', 'uchar'),
        ('blue', 'uchar'),
        ('alpha', 'uchar'),
    ]


        