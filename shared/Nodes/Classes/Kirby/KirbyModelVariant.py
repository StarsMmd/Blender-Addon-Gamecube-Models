from ...Node import Node


# 32-byte (0x20) struct wrapped by Kirby DataGroup. Decoded fields:
#   +0x08 → KirbyModelRef (the path to the JObj root)
#   +0x0C → 8-slot u32 array, populated at runtime by KAR_em_post_load_init
#           with callback pointers from emDataAll[+0x08]
# Other fields are aux pointers / shared-header refs whose semantics are not
# yet decoded — kept as raw uint so the parser doesn't try to dereference them.
class KirbyModelVariant(Node):
    class_name = "Kirby Model Variant"
    fields = [
        ('shared_a', 'uint'),                 # +0x00
        ('shared_b', 'uint'),                 # +0x04
        ('model', 'KirbyModelRef'),           # +0x08 ← the route to Joint
        ('runtime_callbacks', 'uint'),        # +0x0C
        ('common_meta', 'uint'),              # +0x10
        ('shared_c', 'uint'),                 # +0x14
        ('prev_or_alt', 'uint'),              # +0x18
        ('end_marker', 'uint'),               # +0x1C
    ]
