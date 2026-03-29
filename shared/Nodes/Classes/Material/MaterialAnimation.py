from ...Node import Node

# Material Animation
class MaterialAnimation(Node):
    class_name = "Material Animation"
    fields = [
        ('next', 'MaterialAnimation'),
        ('animation', 'Animation'),
        ('texture_animation', 'TextureAnimation'),
        ('render_animation', 'RenderAnimation'),
    ]
