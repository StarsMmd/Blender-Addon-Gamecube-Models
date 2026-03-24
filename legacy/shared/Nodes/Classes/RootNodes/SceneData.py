from ...Node import Node

# Scene Data
class SceneData(Node):
    class_name = "Scene Data"
    fields = [
        ('models', 'ModelSet[]'),
        ('camera', 'CameraSet'),
        ('lights', 'LightSet[]'),
        ('fog', 'Fog')
    ]





