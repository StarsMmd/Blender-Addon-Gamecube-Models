from ...Node import Node

# Light Animation
class LightAnimation(Node):
    class_name = "Light Animation"
    fields = [
        ('next', 'LightAnimation'),
        ('animation', 'Animation'),
        ('eye_position_animation', 'WObjectAnimation'),
        ('interest_animation', 'WObjectAnimation'),
    ]
