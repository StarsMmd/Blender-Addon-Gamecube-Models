from ...Node import Node

# Light Set
class LightSet(Node):
    class_name = "Light Set"
    fields = [
        ('light', 'Light'),
        ('animations', 'LightAnimation[]'),
    ]
