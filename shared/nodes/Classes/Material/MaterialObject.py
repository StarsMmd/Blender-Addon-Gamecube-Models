from ...Node import Node

# Material Object
class MaterialObject(Node):
    class_name = "Material Object"
    fields = [
        ('class_type', 'string'),
        ('render_mode', 'uint'),
        ('texture', 'Texture'),
        ('material', 'Material'),
        ('render_data', 'Render'),
        ('pe_data', 'PixelEngine'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        self.id = self.address