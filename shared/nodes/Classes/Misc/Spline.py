from ...Node import Node

# Spline
class Spline(Node):
    class_name = "Spline"
    fields = [
        ('flags', 'ushort'),
        ('n', 'ushort'),
        ('f0', 'float'),
        ('s1', 'uint'),
        ('f1', 'float'),
        ('s2', 'uint'),
        ('s3', 'uint'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        # TODO: complete spline implememtation
