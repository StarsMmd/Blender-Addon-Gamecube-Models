from ...Node import Node


# 40-byte (0x28) struct that wraps the HSD Joint root in Kirby Air Ride
# enemy DataGroups. Layout decoded by relocation-pattern analysis of the
# retail KAR dump: see memory/reference_kar_disassembly.md.
class KirbyModelRef(Node):
    class_name = "Kirby Model Ref"
    fields = [
        ('root_joint', 'Joint'),     # +0x00 — the actual JObj hierarchy
        ('joint_count', 'uint'),     # +0x04 — matches walked-tree size
        ('flag1', 'uint'),           # +0x08 — observed =1 across samples
        ('flag2', 'uint'),           # +0x0C — observed =1
        ('flag3', 'uint'),           # +0x10 — observed =1
        ('anim_set_a', 'uint'),      # +0x14 — opaque pointer (likely animation-set descriptor)
        ('anim_set_b', 'uint'),      # +0x18 — opaque pointer
        ('anim_set_c', 'uint'),      # +0x1C — opaque pointer
        ('pad1', 'uint'),            # +0x20
        ('pad2', 'uint'),            # +0x24
    ]
