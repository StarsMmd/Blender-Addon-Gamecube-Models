from ...Node import Node

# Texture Animation
class TextureAnimation(Node):
    class_name = "Texture Animation"
    fields = [
        ('next', 'TextureAnimation'),
        ('id', 'uint'),
        ('animation', 'Animation'),
        ('image_table', 'Image[image_table_count]'),
        ('palette_table', 'Palette[palette_table_count]'),
        ('image_table_count', 'ushort'),
        ('palette_table_count', 'ushort'),
    ]