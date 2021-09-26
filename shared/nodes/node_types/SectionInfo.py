from .. import Node

# Section Info
class SectionInfo(Node):
    class_name = "Section Info"
    length = 8
    fields = [
        ("root_node_pointer", "uint"), # the type of node to parse depends on the section name
        ("section_name", "string")
    ]

    # Parse struct from binary file.
    @classmethod
    def fromBinary(cls, parser, address, isPublic):
        node = parser.parseStruct(cls, address)
        node.isPublic = isPublic
        return node

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder, string_address):
        writeAddress = builder.currentRelativeAddress()

        # The root node is written beforehand so all sections have their trees written before the section info is added
        # at the end in bulk
        builder.write("uint", root_node.address)
        builder.write("uint", string_address)
        
        return writeAddress

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass