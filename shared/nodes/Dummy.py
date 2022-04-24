from .Node import Node

# Dummy Node
class Dummy(Node):
    class_name = "Dummy"
    fields = []

    # Parse struct from binary file.
    def loadFromBinary(self, parser):
        return

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        return

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        return Dummy(0, None)

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass

    def __str__(self):
        return "-> " + self.class_name + " @" + hex(self.address) + " (Not yet implemented)\n"