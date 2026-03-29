from ...Node import Node

# Render
class Render(Node):
    class_name = "Render"
    fields = [
        ('toon_texture', 'Texture'),
        ('grad_texture', 'Texture'),
        ('terminator', 'uint'),
    ]
