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
