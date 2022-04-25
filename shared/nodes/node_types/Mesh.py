from ..Node import Node

# Mesh (aka DObject)
class Mesh(Node):
    class_name = "Mesh"
    fields = [
        ('name', 'string'),
        ('next', 'Mesh'),
        ('mobject', 'MObject'),
        ('pobject', 'PObject')
    ]

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        return builder.writeStruct(self)

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass