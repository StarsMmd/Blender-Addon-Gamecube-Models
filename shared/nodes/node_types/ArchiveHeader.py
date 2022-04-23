from ..Node import Node

# Archive Header
class ArchiveHeader(Node):
    class_name = "Archive Header"
    fields = [
        ('file_size', 'uint'),
        ('data_size', 'uint'),
        ('relocations_count', 'uint'),
        ('public_nodes_count', 'uint'),
        ('external_nodes_count', 'uint')
    ]

    # Parse struct from binary file.
    @classmethod
    def fromBinary(cls, parser, address):
        header = parser.parseStruct(cls, address, None, False)

        header_size = 32
        section_size = 8
        relocations_size = header.relocations_count * 4
        sections_start = header.data_size + relocations_size
        section_count = header.public_nodes_count + header.external_nodes_count
        header.section_names_offset = sections_start + (section_size * section_count)

        parser.registerRelocationTable(header.data_size, header.relocations_count)

        # Parse sections info
        section_addresses = []

        current_offset = sections_start
        for i in range(header.public_nodes_count):
            section_addresses.append( (current_offset, True) )
            current_offset += section_size

        for i in range(header.external_nodes_count):
            section_addresses.append( (current_offset, False) )
            current_offset += section_size

        header.section_addresses = section_addresses

        return header

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