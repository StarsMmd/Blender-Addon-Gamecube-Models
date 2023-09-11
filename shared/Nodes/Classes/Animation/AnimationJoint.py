from ...Node import Node

# Animation Joint
class AnimationJoint(Node):
    class_name = "Animation Joint"
    fields = [
        ('child', 'AnimationJoint'),
        ('next', 'AnimationJoint'),
        ('animation', 'Animation'),
        ('render_animation', 'RenderAnimation'),
        ('flags', 'uint'),
    ]