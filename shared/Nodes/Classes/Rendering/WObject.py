from ...Node import Node

# W Object
class WObject(Node):
    class_name = "W Object"
    fields = [
        ('name', 'string'),
        ('position', 'vec3'),
        ('render', 'Render'),
    ]
