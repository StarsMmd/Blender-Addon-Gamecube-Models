from ...Node import Node

# Frame (aka FObject)
class Frame(Node):
    class_name = "Key Frame"
    fields = [
        ('next', 'Frame'),
        ('length', 'uint'),
        ('start_frame', 'float'),
        ('type', 'uchar'),
        ('frac_value', 'uchar'),
        ('frac_slope', 'uchar'),
        ('ad', 'uint'), # TODO: confirm what kind of data this points to
    ]
