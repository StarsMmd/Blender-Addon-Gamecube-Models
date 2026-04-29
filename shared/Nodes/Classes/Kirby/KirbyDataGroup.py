from ...Node import Node


# Top-level public symbol of every Kirby Air Ride enemy DAT
# (e.g. "emCappyDataGroup", "emBombboneDataGroup"). Holds 1–3 model
# variants. Variants live at offsets +0x00, +0x04, and +0x10 — all three
# slots are consumed identically by KAR's enemy-init function at 0x801FE01C.
class KirbyDataGroup(Node):
    class_name = "Kirby Data Group"
    fields = [
        ('variant_a', 'KirbyModelVariant'),   # +0x00
        ('variant_b', 'KirbyModelVariant'),   # +0x04
        ('aux_08', 'uint'),                   # +0x08 — undecoded
        ('aux_0c', 'uint'),                   # +0x0C — undecoded
        ('variant_c', 'KirbyModelVariant'),   # +0x10
        ('aux_14', 'uint'),                   # +0x14 — undecoded
    ]

    def variants(self):
        """Return the non-null model variants in slot order.

        In: -.
        Out: list[KirbyModelVariant] — variants reachable from this DataGroup.
        """
        return [v for v in (self.variant_a, self.variant_b, self.variant_c) if v is not None]

    def root_joints(self):
        """Return the HSD Joint root of every variant that carries a model.

        In: -.
        Out: list[Joint] — the JObj root for each variant whose ModelRef.root_joint resolved.
        """
        joints = []
        for variant in self.variants():
            model = variant.model
            if model is None:
                continue
            joint = model.root_joint
            if joint is not None:
                joints.append(joint)
        return joints
