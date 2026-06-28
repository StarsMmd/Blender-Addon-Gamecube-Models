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
        ('pixel_engine_data', 'PixelEngine'),
    ]

    # Sysdolphin emits an MObject's child structs with the PixelEngine first,
    # then the texture (and its image), then the material — not field order.
    serialization_field_order = ['pixel_engine_data', 'texture', 'material', 'render_data']

    # A multi-texture material's texture chain is emitted in reverse: the
    # deepest texture (last in the texture.next chain) first, the head last.
    serialization_reverse_chain_fields = ('texture',)

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        self.id = self.address
