from .. import Node

# Section Info
class SectionInfo(Node):
    def __init__(self, blender_obj, address, root_node, section_name, isPublic):
        super().__init__("Section Info", address, blender_obj)
        self.section_name = section_name
        self.isPublic = isPublic
        self.root_node = root_node

    # Parse struct from binary file.
    @classmethod
    def fromBinary(cls, parser, address, isPublic):
        root_pointer = parser.read("uint", address,  0)
        name_pointer = parser.read("uint", address,  4)
        section_name = parser.read("string", name_pointer)

        return ArchiveHeader(None, address, relocation)

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def write(self, builder, string_address):
        writeAddress = builder.currentRelativeAddress()

        # The root node is written separately so all sections have their trees written before the section info is added

        builder.write("uint", root_node.address)
        builder.write("uint", string_address)
        
        return writeAddress

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass