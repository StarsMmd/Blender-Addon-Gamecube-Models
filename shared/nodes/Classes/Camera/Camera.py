from ...Node import Node

# Camera
class Camera(Node):
    class_name = "Camera"
    fields = [
        ('name', 'string'),
        ('flags', 'ushort'),
        ('perspective_flags', 'ushort'),
        ('viewport', 'ushort[4]'),
        ('scissor', 'ushort[4]'),
        ('position', 'WObject'),
        ('interest', 'WObject'),
        ('roll', 'float'),
        ('up_vector', '*vec3'),
        ('near', 'float'),
        ('far', 'float'),
        ('field_of_view', 'float'),
        ('aspect', 'float'),
    ]
