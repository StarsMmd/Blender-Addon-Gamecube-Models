from ...Node import Node

# Camera Set
class CameraSet(Node):
    class_name = "Camera Set"
    fields = [
        ('camera', 'Camera'),
        ('animations', 'CameraAnimation[]'),
    ]

    @classmethod
    def emptySet(cls):
        new_node = CameraSet(0, None)
        new_node.camera = None
        new_node.animations = []
        return new_node

    def build(self, builder):
        pass