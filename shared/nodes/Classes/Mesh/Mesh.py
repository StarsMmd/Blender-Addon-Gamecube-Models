from ...Node import Node

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

    def prepareForBlender(self, builder):
        super().prepareForBlender(builder)
        return
        
        # Add material to sub meshes
        material = self.mobject.blender_material
        pobject = self.pobject
        while pobject:
            pobject.blender_mesh.materials.append(material)
            pobject = pobject.next