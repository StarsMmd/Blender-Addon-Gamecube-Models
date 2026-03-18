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
            wrap_names = {0: 'CLAMP', 1: 'REPEAT', 2: 'MIRROR'}
            parser.logger.debug("Texture 0x%X: image at 0x%X, palette=%s, flags=0x%08X, source=%d, "
                                "wrap_s=%s, wrap_t=%s, repeat_s=%d, repeat_t=%d",
                                self.address, self.image.address,
                                ("0x%X" % self.palette.address) if self.palette else "None",
                                self.flags, self.source,
                                wrap_names.get(self.wrap_s, str(self.wrap_s)),
                                wrap_names.get(self.wrap_t, str(self.wrap_t)),
                                self.repeat_s, self.repeat_t)
            self.decoded_pixels = self.image.loadDataWithPalette(parser, self.palette)
        else:
            parser.logger.debug("Texture 0x%X: no image", self.address)
            self.decoded_pixels = None

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
                self.image_data = self.image.build(builder, self.decoded_pixels)
                builder.cacheImage(image_id, palette_id, self.image_data)

        else:
            self.image_data = None



