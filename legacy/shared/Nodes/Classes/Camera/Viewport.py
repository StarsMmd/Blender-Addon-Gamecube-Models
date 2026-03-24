from ...Node import Node

# Viewport
class Viewport(Node):
    class_name = "Viewport"
    fields = [
        ('ix', 'ushort'),
        ('iw', 'ushort'),
        ('iy', 'ushort'),
        ('ih', 'ushort'),
    ]
