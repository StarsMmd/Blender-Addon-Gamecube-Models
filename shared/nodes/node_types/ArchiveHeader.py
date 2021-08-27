from .. import Node

# Archive Header
class ArchiveHeader(Node):
    length = 20

    def __init__(self, blender_obj, address, file_size, data_size, relocations_count, public_nodes_count, external_nodes_count):
        super().__init__("Archive Header", address, blender_obj)
        self.file_size = file_size
        self.data_size = data_size
        self.relocations_count  = relocations_count
        self.public_nodes_count = public_nodes_count
        self.external_nodes_count = external_nodes_count


    # Parse struct from binary file.
    @classmethod
    def fromBinary(cls, parser, address):
        file_size            = parser.read("uint", address,  0, False)
        data_size            = parser.read("uint", address,  4, False)
        relocations_count    = parser.read("uint", address,  8, False)
        public_nodes_count   = parser.read("uint", address, 12, False)
        external_nodes_count = parser.read("uint", address, 16, False)

        return ArchiveHeader(None, address, file_size, data_size, relocations_count, public_nodes_count, external_nodes_count)

    # Make approximation HSD struct from blender data.
    @classmethod
    def fromBlender(cls, blender_obj):
        pass

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def write(self, builder):

        builder.write("uint", self.file_size,             0, False)
        builder.write("uint", self.data_size,             4, False)
        builder.write("uint", self.relocations_count,     8, False)
        builder.write("uint", self.public_nodes_count,   12, False)
        builder.write("uint", self.external_nodes_count, 16, False)
        
        return 0

    # Make approximation Blender object from HSD data.
    def toBlender(self, context):
        pass