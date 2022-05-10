from ...Node import Node

# Light Set
class LightSet(Node):
    class_name = "Light Set"
    fields = [
        ('light', 'Light'),
        ('animations', 'LightAnimation[]'),
    ]

    @classmethod
    def emptySet(cls):
        new_node = LightSet(0, None)
        new_node.light = None
        new_node.animations = []
        return new_node