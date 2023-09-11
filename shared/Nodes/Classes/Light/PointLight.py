from ...Node import Node

# Point Light
class PointLight(Node):
    class_name = "Point Light"
    fields = [
        ('reference_br', 'float'),
        ('reference_distance', 'float'),
        # TODO: confirm if there's a third field here or not
    ]

 