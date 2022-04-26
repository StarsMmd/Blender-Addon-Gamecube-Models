from ...Node import Node

# RGBA Color (aka GBAColor)
class RGBAColor(Node):
    class_name = "RGBA Color"
    is_cachable = False
    fields = [
        ('red', 'uchar'),
        ('green', 'uchar'),
        ('blue', 'uchar'),
        ('alpha', 'uchar'),
    ]

