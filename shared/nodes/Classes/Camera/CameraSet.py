from ...Node import Node

# Camera Set
class CameraSet(Node):
    class_name = "Camera Set"
    fields = [
        ('camera', 'Camera'),
        ('camera_animations', 'CameraAnimation[]'),
    ]
