from ...Node import Node


# Texture Animation
class TextureAnimation(Node):
    class_name = "Texture Animation"
    # image_table / palette_table are double pointers: each holds the address
    # of a table of `*_count` pointers, and every table entry points to an
    # Image / Palette struct (frame-swap texture animation). The generic
    # machinery handles both directions: the parser injects the count fields
    # into the array bounds and reads the pointer table, and
    # Node.writePrivateData materializes the table on write.
    fields = [
        ('next', 'TextureAnimation'),
        ('id', 'uint'),
        ('animation', 'Animation'),
        ('image_table', '*(Image[image_table_count])'),
        ('palette_table', '*(Palette[palette_table_count])'),
        ('image_table_count', 'ushort'),
        ('palette_table_count', 'ushort'),
    ]
