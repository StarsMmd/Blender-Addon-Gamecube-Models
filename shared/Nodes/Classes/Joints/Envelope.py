from ...Node import Node

# Envelope
class EnvelopeList(Node):
    class_name = "Envelope List"
    is_cachable = False
    fields = [
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        # We need to manually parse the envelope list here rather than relying on the automatic parsing of Envelope[]
        # because the terminator is just 4 null bytes rather than 8 null bytes to match the size of a null Envelope

        envelopes = []
        current_offset = self.address
        envelope = parser.read("Envelope", current_offset)
        while envelope.joint:
            envelopes.append(envelope)
            current_offset += 8
            envelope = parser.read("Envelope", current_offset)

        self.envelopes = envelopes
        parser.logger.debug("EnvelopeList 0x%X: %d envelopes", self.address, len(envelopes))

    def allocationSize(self):
        # Each envelope is 8 bytes (joint pointer + weight float)
        # + 8 byte null terminator (full null Envelope: zero joint ptr + zero weight)
        return len(self.envelopes) * 8 + 8

    def writeBinary(self, builder):
        if self.address is None:
            return
        absolute_address = self.address + builder.DAT_header_length
        builder.seek(absolute_address)
        import struct
        for envelope in self.envelopes:
            joint_addr = envelope.joint.address if envelope.joint and envelope.joint.address is not None else 0
            if joint_addr != 0:
                builder.relocations.append(builder._currentRelativeAddress())
            builder.file.write(struct.pack('>I', joint_addr))
            builder.file.write(struct.pack('>f', envelope.weight))
        # Null terminator — full 8-byte null Envelope (joint=0, weight=0.0)
        builder.file.write(struct.pack('>I', 0))
        builder.file.write(struct.pack('>f', 0.0))


# Envelope
class Envelope(Node):
    class_name = "Envelope"
    fields = [
        ('joint', 'Joint'),
        ('weight', 'float'),
    ]
