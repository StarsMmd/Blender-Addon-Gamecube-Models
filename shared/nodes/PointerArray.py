from . import Node

# Generic Pointer Array
class PointerArray(Node):
    node_class = Node
    node_type  = "Node"

    def __init__(self, blender_obj, address, nodes, node_type):
        super().__init__(node_type + " Array", address, blender_obj)
        self.nodes = nodes

    # Parse struct from binary file.
    @classmethod
    def fromBinary(cls, parser, address):
        nodes = []
        current_address = address
        next_pointer = parser.read("uint", current_address)

        while next_pointer != 0:
            new_node = parser.parseNode(cls.node_class, next_pointer)
            nodes.append(new_node)
            current_address += 4
            next_pointer = parser.read("uint", current_address)

        return PointerArray(None, address, nodes, cls.node_type)

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        nodes = []
        for obj in blender_obj:
            nodes.append(cls.node_class.fromBlender(obj))

        return PointerArray(blender_obj, None, nodes, cls.node_type)

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def write(self, builder):

        pointers = []

        for node in nodes:
            pointers.append(node.write(builder))

        writeAddress = builder.currentRelativeAddress()

        for pointer in pointers:
            builder.write("uint", pointer)

        builder.write("uint", 0) # Mark end of array
        
        return writeAddress

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        for node in node:
            node.toBlender(context)








        