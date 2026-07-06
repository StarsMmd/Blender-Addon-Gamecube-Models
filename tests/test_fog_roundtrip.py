"""Fog round-trip: describe_fog → compose_fog.

Some map archives carry a Fog node in their SceneData. describe must lift
its fields into IRFog and compose must re-emit an identical Fog node, so
the NIN round-trip stops counting fog as a miss. Fog Z distances are
carried verbatim (GC units) so the raw float bits survive exactly.
"""
import struct
from types import SimpleNamespace

from importer.phases.describe.helpers.fog import describe_fog
from exporter.phases.compose.helpers.fog import compose_fog
from shared.IR.fog import IRFog


def _make_color(r, g, b, a):
    return SimpleNamespace(red=r, green=g, blue=b, alpha=a)


def _make_fog(type=0, adj=None, start_z=0.0, end_z=0.0, color=None):
    return SimpleNamespace(type=type, adj=adj, start_z=start_z,
                           end_z=end_z, color=color)


class TestDescribeFog:

    def test_none_returns_none(self):
        assert describe_fog(None) is None

    def test_fields_lifted(self):
        node = _make_fog(type=3, start_z=100.0, end_z=5000.0,
                         color=_make_color(10, 20, 30, 40))
        ir = describe_fog(node)
        assert ir.type == 3
        assert ir.start_z == 100.0 and ir.end_z == 5000.0
        assert ir.color == (10, 20, 30, 40)
        assert ir.has_adj is False

    def test_adj_presence_detected(self):
        node = _make_fog(adj=object())
        assert describe_fog(node).has_adj is True


class TestComposeFog:

    def test_none_returns_none(self):
        assert compose_fog(None) is None

    def test_fields_emitted(self):
        ir = IRFog(type=7, start_z=1.0, end_z=2.0, color=(1, 2, 3, 4))
        node = compose_fog(ir)
        assert node.type == 7
        assert node.start_z == 1.0 and node.end_z == 2.0
        assert (node.color.red, node.color.green,
                node.color.blue, node.color.alpha) == (1, 2, 3, 4)
        assert node.adj is None

    def test_adj_emitted_when_present(self):
        node = compose_fog(IRFog(has_adj=True))
        assert node.adj is not None


class TestFogBRMistMapping:
    """IR → BR (World Mist) → IR is a deliberately lossy native mapping.

    The mist range (start / depth) preserves start_z/end_z, but the GX fog
    type collapses onto Blender's three falloff modes and the color alpha is
    dropped — exact game values are not expected to survive.
    """

    def test_range_and_falloff_map_through_mist(self):
        from importer.phases.plan.helpers.scene import plan_fogs as to_br
        from exporter.phases.plan.helpers.scene import plan_fogs as to_ir
        from shared.BR.fog import BRFog

        orig = [IRFog(type=2, start_z=10.0, end_z=60.0, color=(0, 51, 204, 64))]
        br = to_br(orig)
        assert len(br) == 1 and isinstance(br[0], BRFog)
        assert br[0].mist_start == 10.0
        assert br[0].mist_depth == 50.0
        assert br[0].falloff == 'LINEAR'          # GX type 2 → LINEAR
        assert abs(br[0].color[2] - 204 / 255) < 1e-4

        rec = to_ir(br)[0]
        assert rec.start_z == 10.0 and rec.end_z == 60.0  # range survives
        assert rec.type == 2                               # LINEAR → GX 2
        assert rec.color[:3] == (0, 51, 204)               # RGB survives
        assert rec.color[3] == 255                         # alpha lost → opaque

    def test_unknown_type_falls_back_to_linear(self):
        from importer.phases.plan.helpers.scene import plan_fogs as to_br
        # Degenerate map fog (pointer-garbage type) → LINEAR, no crash.
        br = to_br([IRFog(type=0x31C1E8, start_z=1.5, end_z=2.5, color=(1, 2, 3, 4))])
        assert br[0].falloff == 'LINEAR'

    def test_empty_lists(self):
        from importer.phases.plan.helpers.scene import plan_fogs as to_br
        from exporter.phases.plan.helpers.scene import plan_fogs as to_ir
        assert to_br(None) == [] and to_br([]) == []
        assert to_ir(None) == [] and to_ir([]) == []


class TestFogRoundTrip:

    def test_degenerate_float_bits_survive(self):
        # A map's fog can be leftover pointer values reinterpreted as floats
        # (denormals). Carrying them verbatim must preserve the exact bits.
        raw_start = struct.unpack('>f', struct.pack('>I', 0x0031C2EC))[0]
        raw_end = struct.unpack('>f', struct.pack('>I', 0x0031C318))[0]
        node = _make_fog(type=0x31C1E8, start_z=raw_start, end_z=raw_end,
                         color=_make_color(0, 49, 195, 64))

        ir = describe_fog(node)
        out = compose_fog(ir)

        assert struct.pack('>f', out.start_z) == struct.pack('>I', 0x0031C2EC)
        assert struct.pack('>f', out.end_z) == struct.pack('>I', 0x0031C318)
        assert out.type == 0x31C1E8
