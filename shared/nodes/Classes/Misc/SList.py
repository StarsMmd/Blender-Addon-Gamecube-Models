from ...Node import Node

# S List
class SList(Node):
    class_name = "S List"
    fields = [
        ('next', 'SList'),
        ('data', 'uint'), # TODO: confirm what kind of data this points to
    ]

