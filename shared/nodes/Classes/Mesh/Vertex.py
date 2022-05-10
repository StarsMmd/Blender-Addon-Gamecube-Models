from ....Constants import *
from ...Node import Node

# Vertex (aka vtxdesc)
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

    def is_tex(self):
        return (self.attribute == gx.GX_VA_TEX0 or
            self.attribute == gx.GX_VA_TEX1 or
            self.attribute == gx.GX_VA_TEX2 or
            self.attribute == gx.GX_VA_TEX3 or
            self.attribute == gx.GX_VA_TEX4 or
            self.attribute == gx.GX_VA_TEX5 or
            self.attribute == gx.GX_VA_TEX6 or
            self.attribute == gx.GX_VA_TEX7)
        