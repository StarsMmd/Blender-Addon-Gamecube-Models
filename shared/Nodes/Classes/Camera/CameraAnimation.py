from ...Node import Node

# Camera Animation
class CameraAnimation(Node):
    class_name = "Camera Animation"
    fields = [
        ('animation', 'Animation'),
        ('eye_position_animation', 'WObjectAnimation'),
        ('interest_animation', 'WObjectAnimation'),
    ]
