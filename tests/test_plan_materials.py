"""Unit tests for the Plan phase's IR materials → BR materials helper.

Focuses on decision logic that was previously untestable: blend-mode
selection, TEV stage wiring, per-axis wrap-mode chains, and pixel-engine
effect branches. The BRGraphBuilder means we can assert on node types
and connectivity without touching bpy.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from shared.IR.enums import (
    ColorSource, LightingModel, CoordType, WrapMode,
    LayerBlendMode, CombinerInputSource, CombinerOp, CombinerBias,
    CombinerScale, OutputBlendEffect, BlendFactor, LightmapChannel,
)
from shared.BR.materials import BRMaterial, BRNode
from importer.phases.plan.helpers.materials import (
    plan_material,
    BRGraphBuilder,
    _plan_per_axis_wrap,
    _plan_pixel_engine,
    _plan_apply_blend,
    _LAYER_BLEND_OPS,
)


def _stub_ir_material(**overrides):
    """Minimal IRMaterial stub for planning."""
    defaults = dict(
        diffuse_color=(1.0, 1.0, 1.0, 1.0),
        specular_color=(1.0, 1.0, 1.0, 1.0),
        ambient_color=(0.3, 0.3, 0.3, 1.0),
        alpha=1.0,
        shininess=50.0,
        enable_specular=False,
        lighting=LightingModel.LIT,
        color_source=ColorSource.MATERIAL,
        alpha_source=ColorSource.MATERIAL,
        texture_layers=[],
        is_translucent=False,
        fragment_blending=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _count_nodes_by_type(br_material):
    counts = {}
    for node in br_material.node_graph.nodes:
        counts[node.node_type] = counts.get(node.node_type, 0) + 1
    return counts


class TestPlanMaterialTopLevel:

    def test_minimal_lit_material_has_expected_named_nodes(self):
        """Every lit material should have DiffuseColor + AlphaValue +
        the ambient emission pair + the output."""
        br = plan_material(_stub_ir_material(), name='test_mat')
        assert isinstance(br, BRMaterial)
        names = {n.name for n in br.node_graph.nodes}
        assert 'DiffuseColor' in names
        assert 'AlphaValue' in names
        assert 'dat_ambient_emission' in names
        assert 'dat_ambient_add' in names
        assert 'Material Output' in names

    def test_material_name_and_dedup_key_propagated(self):
        br = plan_material(_stub_ir_material(), name='foo', dedup_key=(1, 2, 3))
        assert br.name == 'foo'
        assert br.dedup_key == (1, 2, 3)

    def test_backface_culling_flag_from_cull_params(self):
        br1 = plan_material(_stub_ir_material(), name='m', cull_front=False, cull_back=False)
        br2 = plan_material(_stub_ir_material(), name='m', cull_front=True, cull_back=False)
        assert br1.use_backface_culling is False
        assert br2.use_backface_culling is True

    def test_has_color_animation_forces_diffuse_color_node_unlit(self):
        """Unlit material with vertex color source — normally no DiffuseColor
        node — must still get one when has_color_animation=True so the
        material animation baker has a target."""
        ir = _stub_ir_material(
            lighting=LightingModel.UNLIT,
            color_source=ColorSource.VERTEX,
        )
        br_no_anim = plan_material(ir, name='m', has_color_animation=False)
        br_anim = plan_material(ir, name='m', has_color_animation=True)
        names_no = {n.name for n in br_no_anim.node_graph.nodes}
        names_anim = {n.name for n in br_anim.node_graph.nodes}
        assert 'DiffuseColor' not in names_no
        assert 'DiffuseColor' in names_anim


class TestPlanPixelEngine:
    """The effect→blend_method + alt_blend_mode mapping."""

    def _run(self, **fb_overrides):
        g = BRGraphBuilder()
        defaults = dict(
            effect=OutputBlendEffect.OPAQUE,
            source_factor=BlendFactor.SRC_ALPHA,
            dest_factor=BlendFactor.INV_SRC_ALPHA,
        )
        defaults.update(fb_overrides)
        fb = SimpleNamespace(**defaults)
        ir_mat = _stub_ir_material(fragment_blending=fb)
        return _plan_pixel_engine(g, ir_mat, ('c', 0), ('a', 0))

    def test_opaque_effect_is_noop(self):
        color, alpha, transparent, alt, blend = self._run(effect=OutputBlendEffect.OPAQUE)
        assert color == ('c', 0)
        assert alpha == ('a', 0)
        assert transparent is False
        assert alt == 'NOTHING'
        assert blend is None

    def test_alpha_blend_picks_hashed(self):
        _, _, transparent, alt, blend = self._run(effect=OutputBlendEffect.ALPHA_BLEND)
        assert transparent is True
        assert alt == 'NOTHING'
        assert blend == 'HASHED'

    def test_additive_sets_alt_blend_only(self):
        _, _, transparent, alt, blend = self._run(effect=OutputBlendEffect.ADDITIVE)
        assert transparent is False
        assert alt == 'ADD'
        assert blend is None

    def test_additive_alpha_is_transparent_add_alpha(self):
        _, _, transparent, alt, _blend = self._run(effect=OutputBlendEffect.ADDITIVE_ALPHA)
        assert transparent is True
        assert alt == 'ADD_ALPHA'

    def test_invisible_zeroes_alpha_and_picks_hashed(self):
        _, alpha, transparent, _alt, blend = self._run(effect=OutputBlendEffect.INVISIBLE)
        # alpha_ref should have been replaced with a newly-added ShaderNodeValue (= 0).
        assert transparent is True
        assert blend == 'HASHED'
        assert alpha != ('a', 0), "alpha ref should be replaced by invisible node"


class TestPlanApplyBlend:

    def test_none_blend_passes_through(self):
        g = BRGraphBuilder()
        prev = ('prev', 0)
        result = _plan_apply_blend(g, prev, ('c', 0), ('a', 0),
                                   LayerBlendMode.NONE, 1.0, is_color=True)
        assert result == prev
        assert len(g._nodes) == 0  # no nodes added

    def test_mix_blend_inserts_mixrgb_with_factor(self):
        g = BRGraphBuilder()
        prev = ('prev', 0)
        result = _plan_apply_blend(g, prev, ('c', 0), ('a', 0),
                                   LayerBlendMode.MIX, 0.7, is_color=True)
        assert result != prev
        assert any(n.node_type == 'ShaderNodeMixRGB' for n in g._nodes)
        # Factor should have propagated to socket 0's default.
        mix = next(n for n in g._nodes if n.node_type == 'ShaderNodeMixRGB')
        assert abs(mix.input_defaults[0] - 0.7) < 1e-9

    def test_replace_sets_factor_zero(self):
        g = BRGraphBuilder()
        _plan_apply_blend(g, ('prev', 0), ('c', 0), ('a', 0),
                          LayerBlendMode.REPLACE, 1.0, is_color=True)
        mix = next(n for n in g._nodes if n.node_type == 'ShaderNodeMixRGB')
        # REPLACE routes cur_color into input 1 and pins factor to 0.
        assert mix.input_defaults[0] == 0.0


class TestPlanPerAxisWrap:
    """The Separate → per-axis wrap op → Combine chain for exporter round-trip."""

    def _run(self, wrap_s, wrap_t):
        g = BRGraphBuilder()
        # Pretend there's a mapping node already named 'Mapping_X'
        g.add_node('ShaderNodeMapping', name='Mapping_0')
        _plan_per_axis_wrap(g, 'Mapping_0', 0, wrap_s, wrap_t)
        return g._nodes

    def test_mirror_produces_pingpong(self):
        nodes = self._run(WrapMode.MIRROR, WrapMode.MIRROR)
        pingpongs = [n for n in nodes
                     if n.node_type == 'ShaderNodeMath'
                     and n.properties.get('operation') == 'PINGPONG']
        assert len(pingpongs) == 2

    def test_repeat_produces_fract(self):
        nodes = self._run(WrapMode.REPEAT, WrapMode.REPEAT)
        fracts = [n for n in nodes
                  if n.properties.get('operation') == 'FRACT']
        assert len(fracts) == 2

    def test_clamp_produces_max_then_min(self):
        nodes = self._run(WrapMode.CLAMP, WrapMode.CLAMP)
        maxes = [n for n in nodes
                 if n.properties.get('operation') == 'MAXIMUM']
        mins = [n for n in nodes
                if n.properties.get('operation') == 'MINIMUM']
        assert len(maxes) == 2
        assert len(mins) == 2

    def test_mixed_per_axis_wrap(self):
        """Asymmetric wraps are allowed — one REPEAT + one CLAMP."""
        nodes = self._run(WrapMode.REPEAT, WrapMode.CLAMP)
        ops = {n.properties.get('operation') for n in nodes
               if n.node_type == 'ShaderNodeMath'}
        assert 'FRACT' in ops
        assert 'MAXIMUM' in ops
        assert 'MINIMUM' in ops


class TestLayerBlendOpsMap:

    def test_every_non_none_layer_blend_mode_has_mapping(self):
        """Every IR LayerBlendMode except NONE/PASS must have a blend op."""
        for mode in LayerBlendMode:
            if mode in (LayerBlendMode.NONE, LayerBlendMode.PASS):
                assert mode not in _LAYER_BLEND_OPS
            else:
                assert mode in _LAYER_BLEND_OPS, f"Missing op for {mode}"
