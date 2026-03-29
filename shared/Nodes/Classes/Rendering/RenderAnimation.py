from ...Node import Node

# Render Animation (HSD_ROBJAnimJoint)
# Linked list of animation objects for Reference Objects (constraints).
# Each node in this list corresponds 1:1 with a Reference (RObj) in the
# Joint's reference chain, providing animation tracks for that constraint.
#
# HSDLib reference: HSD_ROBJAnimJoint (0x08 bytes)
#   0x00: next → ROBJAnimJoint*
#   0x04: aobj → AOBJ* (animation tracks)
class RenderAnimation(Node):
    class_name = "Render Animation"
    fields = [
        ('next', 'RenderAnimation'),
        ('animation', 'Animation'),
    ]
