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


# Envelope
class Envelope(Node):
    class_name = "Envelope"
    fields = [
        ('joint', 'Joint'),
        ('weight', 'float'),
    ]
