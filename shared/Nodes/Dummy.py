from .Node import Node

# Dummy Node
class Dummy(Node):
    class_name = "Dummy"
    is_cachable = False
    fields = []

    # Parse struct from binary file.
    def loadFromBinary(self, parser):
        return

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        return

    def __str__(self):
        return "-> " + self.class_name + " @" + hex(self.address) + " (Node class not found)\n"