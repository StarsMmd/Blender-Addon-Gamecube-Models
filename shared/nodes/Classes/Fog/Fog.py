from ...Node import Node

# Fog
class Fog(Node):
    class_name = "Fog"
    fields = [
        ('type', 'uint'),
        ('adj', 'FogAdj'),
        ('start_z', 'float'),
        ('end_z', 'float'),
        ('color', '@RGBAColor'),
    ]