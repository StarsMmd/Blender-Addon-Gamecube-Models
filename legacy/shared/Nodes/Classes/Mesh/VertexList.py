from ...Node import Node
from ....Errors import *

# Vertex List
class VertexList(Node):
    class_name = "Vertex List"
    fields = [
        ('vertices', '(@Vertex)[]'),
    ]

    # Parse struct from binary file.
    def loadFromBinary(self, parser):
        self.vertices = []
        current_offset = 0
        self.vertex_length = parser.getTypeLength('Vertex')

        found_end_of_list = False
        while not found_end_of_list:
            vertex = parser.read('Vertex', self.address, current_offset)
            if vertex.attribute == 0xFF:
                found_end_of_list = True
            else:
                self.vertices.append(vertex)
                current_offset += self.vertex_length

        parser.logger.debug("VertexList 0x%X: %d vertex descriptors", self.address, len(self.vertices))

    # For any fields which are a pointer where the underlying sub type is a primitive type,
    # write them to the builder's output and replace the field with the address it was written to
    def writePrimitivePointers(self, builder):
        # Write vertex buffer data with deduplication.
        # Multiple VertexLists may share the same vertex buffers (same base_pointer).
        # The builder pre-collects the max size per base_pointer and writes each once.
        if not hasattr(builder, '_vertex_buffer_cache'):
            builder._vertex_buffer_cache = {}

        for vertex in self.vertices:
            # Save original base_pointer before any modification
            if not hasattr(vertex, '_orig_base_pointer'):
                vertex._orig_base_pointer = vertex.base_pointer

        for vertex in self.vertices:
            if hasattr(vertex, 'raw_vertex_data') and vertex.raw_vertex_data:
                orig_bp = vertex._orig_base_pointer
                if orig_bp not in builder._vertex_buffer_cache:
                    # Find the largest raw_vertex_data for this base_pointer across all VertexLists
                    max_data = vertex.raw_vertex_data
                    for other in builder.node_list:
                        if type(other).__name__ == 'VertexList':
                            for ov in other.vertices:
                                obp = getattr(ov, '_orig_base_pointer', ov.base_pointer)
                                if hasattr(ov, 'raw_vertex_data') and ov.raw_vertex_data and obp == orig_bp:
                                    if len(ov.raw_vertex_data) > len(max_data):
                                        max_data = ov.raw_vertex_data
                    # Write the largest buffer once
                    builder.seek(0, 'end')
                    new_addr = builder._currentRelativeAddress()
                    for byte in max_data:
                        builder.write(byte, 'uchar')
                    builder._vertex_buffer_cache[orig_bp] = new_addr

                vertex.base_pointer = builder._vertex_buffer_cache[orig_bp]

            # Let the Vertex handle reloc flag tracking
            vertex.writePrivateData(builder)

    # Tells the builder how many bytes to reserve for this node.
    def allocationSize(self):
        # +1 for the 0xFF terminator vertex
        return self.vertex_length * (len(self.vertices) + 1)

    # Tells the builder how to write this node's data to the binary file.
    # The node should have had its write address allocated by the builder by the time this is called.
    def writeBinary(self, builder):
        for (i, vertex) in enumerate(self.vertices):
            vertex.address = self.address + (i * self.vertex_length)
            vertex.writeBinary(builder)

        # Write terminator vertex (attribute = 0xFF, rest zeroed)
        terminator_address = self.address + (len(self.vertices) * self.vertex_length)
        abs_address = terminator_address + builder.DAT_header_length
        builder.seek(abs_address)
        builder.file.write(b'\x00' * self.vertex_length)
        builder.write(0xFF, 'uint', terminator_address, relative_to_header=True)
        

    # Treat this as one complete node so the vertex nodes are always written in the correct order
    # and with custom logic for the terminator.
    def toList(self):
        return [self]
