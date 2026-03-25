
from ...Node import Node
from ....Constants import *

# Mesh (aka DObject)
class Mesh(Node):
    class_name = "Mesh"
    fields = [
        ('name', 'string'),
        ('next', 'Mesh'),
        ('mobject', 'MaterialObject'),
        ('pobject', 'PObject')
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        self.id = self.address

#This is needed for correctly applying all this envelope stuff
