from ...Node import Node

# Material
class Material(Node):
    class_name = "Material"
    fields = [
        ('ambient', '@RGBAColor'),
        ('diffuse', '@RGBAColor'),
        ('specular', '@RGBAColor'),
        ('alpha', 'float'),
        ('shininess', 'float'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        self.ambient.normalize()
        self.diffuse.normalize()
        self.specular.normalize()