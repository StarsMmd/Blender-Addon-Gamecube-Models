from ...Node import Node

# Bound Box
class BoundBox(Node):
    class_name = "Bound Box"
    fields = [
        ('unknown_1', 'ushort'),
        ('unknown_2', 'uint'),
        # TODO: Figure out the size and meaning of the data which follows this
    ]

