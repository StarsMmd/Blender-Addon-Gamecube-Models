from ...Node import Node

# Envelope
class Envelope(Node):
    class_name = "Envelope"
    fields = [
        ('joint', 'Joint'),
        ('weight', 'float'),
    ]
