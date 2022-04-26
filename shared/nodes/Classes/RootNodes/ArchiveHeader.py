from ...Node import Node

# Archive Header
class ArchiveHeader(Node):
    class_name = "Archive Header"
    is_cachable = False
    fields = [
        ('file_size', 'uint'),
        ('data_size', 'uint'),
        ('relocations_count', 'uint'),
        ('public_nodes_count', 'uint'),
        ('external_nodes_count', 'uint')
    ]

    def __init__(self, address, blender_obj):
        super().__init__(address, blender_obj)
        self.length = 32

    # Parse struct from binary file.
    def loadFromBinary(self, parser):
        parser.parseNode(self, relative_to_header=False)

        header_size = 32
        section_size = 8
        relocations_size = self.relocations_count * 4
        sections_start = self.data_size + relocations_size
        section_count = self.public_nodes_count + self.external_nodes_count
        self.section_names_offset = sections_start + (section_size * section_count)

        parser.registerRelocationTable(self.data_size, self.relocations_count)

        # Parse sections info
        section_addresses = []

        current_offset = sections_start
        for i in range(self.public_nodes_count):
            section_addresses.append( (current_offset, True) )
            current_offset += section_size

        for i in range(self.external_nodes_count):
            section_addresses.append( (current_offset, False) )
            current_offset += section_size

        self.section_addresses = section_addresses
