from ...Node import Node

# Animation
class Animation(Node):
    class_name = "Animation"
    fields = [
        ('flags', 'uint'),
        ('end_frame', 'float'),
        ('frame', 'Frame'),
        ('joint', 'Joint'),
    ]