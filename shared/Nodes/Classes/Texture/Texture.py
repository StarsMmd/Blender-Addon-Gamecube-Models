from ...Node import Node

# Texture (aka TObject)
class Texture(Node):
    class_name = "Texture"
    fields = [
        ('name', 'string'),
        ('next', 'Texture'),
        ('texture_id', 'uint'),
        ('source', 'uint'),
        ('rotation', 'vec3'),
        ('scale', 'vec3'),
        ('translation', 'vec3'),
        ('wrap_s', 'uint'),
        ('wrap_t', 'uint'),
        ('repeat_s', 'uchar'),
        ('repeat_t', 'uchar'),
        ('flags', 'uint'),
        ('blending', 'float'),
        ('mag_filter', 'uint'),
        ('image', 'Image'),
        ('palette', 'Palette'),
        ('lod', 'TextureLOD'),
        ('tev', 'TextureTEV'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        self.id = self.address
        if self.image:
            palette_data = None if self.palette == None else self.palette.data
            self.image.loadDataWithPalette(parser, palette_data)

    def build(self, builder):
        if self.image:
            image_id = self.image.id
            palette_id = 0
            if self.palette:
                palette_id = self.palette.id

            cached_image = builder.getCachedImage(image_id, palette_id)
            if cached_image:
                self.image_data = cached_image

            else:
                self.image_data = self.image.build(builder)
                builder.cacheImage(image_id, palette_id, self.image_data)

        else:
            self.image_data = None



