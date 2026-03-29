"""Tests for phases/describe/helpers/materials.py — material description."""
import io
import struct
import pytest

from importer.phases.parse.helpers.dat_parser import DATParser
from importer.phases.describe.helpers.materials import (
    describe_material, _tev_color_value, _map_color_source, _map_alpha_source,
    _map_coord_type, _map_wrap_mode, _map_interpolation,
    _map_color_blend, _map_alpha_blend, _map_lightmap_channel,
    _resolve_blend_effect, _describe_tev,
)
from shared.IR.material import IRMaterial, IRTextureLayer, ColorCombiner
from shared.IR.enums import (
    ColorSource, LightingModel, CoordType, WrapMode, TextureInterpolation,
    LayerBlendMode, LightmapChannel, CombinerInputSource, CombinerOp,
    CombinerBias, CombinerScale, OutputBlendEffect, BlendFactor,
)
from shared.Constants.hsd import *
from shared.Constants.gx import *
from shared.Nodes.Classes.Material.MaterialObject import MaterialObject
from shared.Nodes.Classes.Material.Material import Material
from shared.Nodes.Classes.Texture.TextureTEV import TextureTEV
from shared.Nodes.Classes.Rendering.PixelEngine import PixelEngine
from tests.helpers import (
    build_minimal_dat, build_material, build_material_object, build_pixel_engine,
    MATERIAL_SIZE, MATERIALOBJECT_SIZE, PIXELENGINE_SIZE,
)


def _parse(cls, offset, data):
    dat_bytes = build_minimal_dat(data)
    parser = DATParser(io.BytesIO(dat_bytes), {})
    node = cls(offset, None)
    node.loadFromBinary(parser)
    return node


# ---------------------------------------------------------------------------
# Color source mapping
# ---------------------------------------------------------------------------

class TestMapColorSource:

    def test_lit_material(self):
        assert _map_color_source(RENDER_DIFFUSE_MAT, True) == ColorSource.MATERIAL

    def test_lit_vertex(self):
        assert _map_color_source(RENDER_DIFFUSE_VTX, True) == ColorSource.VERTEX

    def test_lit_both(self):
        assert _map_color_source(RENDER_DIFFUSE_BOTH, True) == ColorSource.BOTH

    def test_unlit_material(self):
        assert _map_color_source(RENDER_DIFFUSE_MAT, False) == ColorSource.MATERIAL

    def test_unlit_vertex(self):
        assert _map_color_source(RENDER_DIFFUSE_VTX, False) == ColorSource.VERTEX

    def test_unlit_both(self):
        assert _map_color_source(RENDER_DIFFUSE_BOTH, False) == ColorSource.BOTH


class TestMapAlphaSource:

    def test_alpha_material(self):
        assert _map_alpha_source(RENDER_ALPHA_MAT, True) == ColorSource.MATERIAL

    def test_alpha_vertex(self):
        assert _map_alpha_source(RENDER_ALPHA_VTX, True) == ColorSource.VERTEX

    def test_alpha_both(self):
        assert _map_alpha_source(RENDER_ALPHA_BOTH, True) == ColorSource.BOTH

    def test_alpha_compat_fallback(self):
        """RENDER_ALPHA_COMPAT (0) should default to MATERIAL."""
        assert _map_alpha_source(0, True) == ColorSource.MATERIAL


# ---------------------------------------------------------------------------
# Texture coordinate / wrap / interpolation mapping
# ---------------------------------------------------------------------------

class TestTextureMappings:

    def test_coord_uv(self):
        assert _map_coord_type(TEX_COORD_UV) == CoordType.UV

    def test_coord_reflection(self):
        assert _map_coord_type(TEX_COORD_REFLECTION) == CoordType.REFLECTION

    def test_wrap_repeat(self):
        assert _map_wrap_mode(GX_REPEAT) == WrapMode.REPEAT

    def test_wrap_clamp(self):
        assert _map_wrap_mode(GX_CLAMP) == WrapMode.CLAMP

    def test_wrap_mirror(self):
        assert _map_wrap_mode(GX_MIRROR) == WrapMode.MIRROR

    def test_interp_nearest(self):
        assert _map_interpolation(GX_NEAR) == TextureInterpolation.CLOSEST

    def test_interp_linear(self):
        assert _map_interpolation(GX_LINEAR) == TextureInterpolation.LINEAR

    def test_interp_cubic(self):
        assert _map_interpolation(GX_LIN_MIP_LIN) == TextureInterpolation.CUBIC


# ---------------------------------------------------------------------------
# Layer blend mode mapping
# ---------------------------------------------------------------------------

class TestBlendMappings:

    def test_color_blend_none(self):
        assert _map_color_blend(TEX_COLORMAP_NONE) == LayerBlendMode.NONE

    def test_color_blend_modulate(self):
        assert _map_color_blend(TEX_COLORMAP_MODULATE) == LayerBlendMode.MULTIPLY

    def test_color_blend_add(self):
        assert _map_color_blend(TEX_COLORMAP_ADD) == LayerBlendMode.ADD

    def test_color_blend_replace(self):
        assert _map_color_blend(TEX_COLORMAP_REPLACE) == LayerBlendMode.REPLACE

    def test_color_blend_alpha_mask(self):
        assert _map_color_blend(TEX_COLORMAP_ALPHA_MASK) == LayerBlendMode.ALPHA_MASK

    def test_alpha_blend_none(self):
        assert _map_alpha_blend(TEX_ALPHAMAP_NONE) == LayerBlendMode.NONE

    def test_alpha_blend_modulate(self):
        assert _map_alpha_blend(TEX_ALPHAMAP_MODULATE) == LayerBlendMode.MULTIPLY

    def test_alpha_blend_replace(self):
        assert _map_alpha_blend(TEX_ALPHAMAP_REPLACE) == LayerBlendMode.REPLACE


# ---------------------------------------------------------------------------
# Lightmap channel mapping
# ---------------------------------------------------------------------------

class TestLightmapMapping:

    def test_diffuse(self):
        assert _map_lightmap_channel(TEX_LIGHTMAP_DIFFUSE) == LightmapChannel.DIFFUSE

    def test_specular(self):
        assert _map_lightmap_channel(TEX_LIGHTMAP_SPECULAR) == LightmapChannel.SPECULAR

    def test_ambient(self):
        assert _map_lightmap_channel(TEX_LIGHTMAP_AMBIENT) == LightmapChannel.AMBIENT

    def test_none(self):
        assert _map_lightmap_channel(0) == LightmapChannel.NONE


# ---------------------------------------------------------------------------
# Pixel engine / blend effect resolution
# ---------------------------------------------------------------------------

class TestResolveBlendEffect:

    def _make_pe(self, **kwargs):
        """Build a minimal PE-like namespace."""
        from types import SimpleNamespace
        defaults = dict(type=0, source_factor=0, destination_factor=0, logic_op=0)
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_opaque(self):
        pe = self._make_pe(type=GX_BM_NONE)
        assert _resolve_blend_effect(pe) == OutputBlendEffect.OPAQUE

    def test_alpha_blend(self):
        pe = self._make_pe(type=GX_BM_BLEND, source_factor=GX_BL_SRCALPHA,
                           destination_factor=GX_BL_INVSRCALPHA)
        assert _resolve_blend_effect(pe) == OutputBlendEffect.ALPHA_BLEND

    def test_inverse_alpha_blend(self):
        pe = self._make_pe(type=GX_BM_BLEND, source_factor=GX_BL_INVSRCALPHA,
                           destination_factor=GX_BL_SRCALPHA)
        assert _resolve_blend_effect(pe) == OutputBlendEffect.INVERSE_ALPHA_BLEND

    def test_additive(self):
        pe = self._make_pe(type=GX_BM_BLEND, source_factor=GX_BL_ONE,
                           destination_factor=GX_BL_ONE)
        assert _resolve_blend_effect(pe) == OutputBlendEffect.ADDITIVE

    def test_multiply(self):
        pe = self._make_pe(type=GX_BM_BLEND, source_factor=GX_BL_DSTCLR,
                           destination_factor=GX_BL_ZERO)
        assert _resolve_blend_effect(pe) == OutputBlendEffect.MULTIPLY

    def test_invisible(self):
        pe = self._make_pe(type=GX_BM_BLEND, source_factor=GX_BL_ZERO,
                           destination_factor=GX_BL_ONE)
        assert _resolve_blend_effect(pe) == OutputBlendEffect.INVISIBLE

    def test_black(self):
        pe = self._make_pe(type=GX_BM_BLEND, source_factor=GX_BL_ZERO,
                           destination_factor=GX_BL_ZERO)
        assert _resolve_blend_effect(pe) == OutputBlendEffect.BLACK


# ---------------------------------------------------------------------------
# TEV color value extraction
# ---------------------------------------------------------------------------

class TestTevColorValue:

    def test_already_normalized_values(self):
        """TEV color registers are normalized in parsing — no second /255."""
        from types import SimpleNamespace
        color = SimpleNamespace(red=0.5, green=0.25, blue=1.0, alpha=0.75)
        result = _tev_color_value(color)
        assert abs(result[0] - 0.5) < 1e-6
        assert abs(result[1] - 0.25) < 1e-6
        assert abs(result[2] - 1.0) < 1e-6
        assert abs(result[3] - 0.75) < 1e-6

    def test_no_color_attrs(self):
        """Object without color attributes returns default black."""
        result = _tev_color_value(object())
        assert result == (0.0, 0.0, 0.0, 1.0)

    def test_full_white(self):
        from types import SimpleNamespace
        color = SimpleNamespace(red=1.0, green=1.0, blue=1.0, alpha=1.0)
        result = _tev_color_value(color)
        assert result == (1.0, 1.0, 1.0, 1.0)

    def test_zero(self):
        from types import SimpleNamespace
        color = SimpleNamespace(red=0.0, green=0.0, blue=0.0, alpha=0.0)
        result = _tev_color_value(color)
        assert result == (0.0, 0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# TEV combiner description
# ---------------------------------------------------------------------------

class TestDescribeTev:

    def _make_tev(self, active=0, color_op=0, alpha_op=0,
                  color_bias=0, alpha_bias=0, color_scale=0, alpha_scale=0,
                  color_clamp=0, alpha_clamp=0,
                  color_a=0, color_b=0, color_c=0, color_d=0,
                  alpha_a=0, alpha_b=0, alpha_c=0, alpha_d=0):
        """Build a minimal TEV-like object."""
        from types import SimpleNamespace
        konst = SimpleNamespace(red=0.5, green=0.5, blue=0.5, alpha=1.0)
        tev0 = SimpleNamespace(red=0.0, green=0.0, blue=0.0, alpha=0.0)
        tev1 = SimpleNamespace(red=0.0, green=0.0, blue=0.0, alpha=0.0)
        return SimpleNamespace(
            active=active, color_op=color_op, alpha_op=alpha_op,
            color_bias=color_bias, alpha_bias=alpha_bias,
            color_scale=color_scale, alpha_scale=alpha_scale,
            color_clamp=color_clamp, alpha_clamp=alpha_clamp,
            color_a=color_a, color_b=color_b, color_c=color_c, color_d=color_d,
            alpha_a=alpha_a, alpha_b=alpha_b, alpha_c=alpha_c, alpha_d=alpha_d,
            konst=konst, tev0=tev0, tev1=tev1,
        )

    def test_no_active_stages(self):
        tev = self._make_tev(active=0)
        assert _describe_tev(tev) is None

    def test_color_stage_only(self):
        tev = self._make_tev(
            active=TOBJ_TEVREG_ACTIVE_COLOR_TEV,
            color_a=GX_CC_ZERO, color_b=GX_CC_TEXC,
            color_c=GX_CC_ONE, color_d=GX_CC_ZERO,
            color_op=GX_TEV_ADD,
            color_bias=GX_TB_ZERO, color_scale=GX_CS_SCALE_1,
            color_clamp=GX_TRUE,
        )
        result = _describe_tev(tev)
        assert isinstance(result, ColorCombiner)
        assert result.color is not None
        assert result.alpha is None
        assert result.color.input_a.source == CombinerInputSource.ZERO
        assert result.color.input_b.source == CombinerInputSource.TEXTURE_COLOR
        assert result.color.operation == CombinerOp.ADD
        assert result.color.clamp is True

    def test_alpha_stage_only(self):
        tev = self._make_tev(
            active=TOBJ_TEVREG_ACTIVE_ALPHA_TEV,
            alpha_a=GX_CA_ZERO, alpha_b=GX_CA_TEXA,
            alpha_c=GX_CA_ZERO, alpha_d=GX_CA_ZERO,
            alpha_op=GX_TEV_ADD,
            alpha_bias=GX_TB_ZERO, alpha_scale=GX_CS_SCALE_1,
            alpha_clamp=0,
        )
        result = _describe_tev(tev)
        assert result.color is None
        assert result.alpha is not None
        assert result.alpha.input_b.source == CombinerInputSource.TEXTURE_ALPHA
        assert result.alpha.clamp is False

    def test_konst_rgb_input(self):
        tev = self._make_tev(
            active=TOBJ_TEVREG_ACTIVE_COLOR_TEV,
            color_a=TOBJ_TEV_CC_KONST_RGB, color_b=GX_CC_ZERO,
            color_c=GX_CC_ZERO, color_d=GX_CC_ZERO,
            color_op=GX_TEV_ADD,
            color_bias=GX_TB_ZERO, color_scale=GX_CS_SCALE_1,
        )
        result = _describe_tev(tev)
        assert result.color.input_a.source == CombinerInputSource.CONSTANT
        assert result.color.input_a.channel == "RGB"
        assert result.color.input_a.value == (0.5, 0.5, 0.5, 1.0)

    def test_subtract_op(self):
        tev = self._make_tev(
            active=TOBJ_TEVREG_ACTIVE_COLOR_TEV,
            color_a=GX_CC_ZERO, color_b=GX_CC_ZERO,
            color_c=GX_CC_ZERO, color_d=GX_CC_ZERO,
            color_op=GX_TEV_SUB,
            color_bias=GX_TB_ZERO, color_scale=GX_CS_SCALE_1,
        )
        result = _describe_tev(tev)
        assert result.color.operation == CombinerOp.SUBTRACT

    def test_bias_plus_half(self):
        tev = self._make_tev(
            active=TOBJ_TEVREG_ACTIVE_COLOR_TEV,
            color_a=GX_CC_ZERO, color_b=GX_CC_ZERO,
            color_c=GX_CC_ZERO, color_d=GX_CC_ZERO,
            color_op=GX_TEV_ADD,
            color_bias=GX_TB_ADDHALF, color_scale=GX_CS_SCALE_2,
        )
        result = _describe_tev(tev)
        assert result.color.bias == CombinerBias.PLUS_HALF
        assert result.color.scale == CombinerScale.SCALE_2


# ---------------------------------------------------------------------------
# Full describe_material — integration tests
# ---------------------------------------------------------------------------

class TestDescribeMaterial:
    """Integration tests for describe_material with parsed node trees."""

    def _build_mobj_data(self, render_mode=0, diffuse=(128, 128, 128, 255),
                         ambient=(64, 64, 64, 255), specular=(255, 255, 255, 255),
                         alpha=1.0, shininess=50.0, pe_data=None):
        """Build binary for a MaterialObject with an inline Material.

        Layout:
          [0]   MaterialObject (24 bytes) — material_ptr points to Material at 24
          [24]  Material (20 bytes) — inline colors
          [44]  PixelEngine (12 bytes) — optional
        """
        mat_offset = MATERIALOBJECT_SIZE
        pe_offset = mat_offset + MATERIAL_SIZE if pe_data else 0

        mobj_data = build_material_object(
            render_mode=render_mode,
            material_ptr=mat_offset,
            pixel_engine_data_ptr=pe_offset,
        )
        mat_data = build_material(
            ambient=ambient, diffuse=diffuse, specular=specular,
            alpha=alpha, shininess=shininess,
        )
        data = mobj_data + mat_data
        if pe_data:
            data += pe_data

        # Relocation table: material_ptr and optionally pe_ptr
        relocs = [12]  # offset 12 = material_ptr in MaterialObject
        if pe_data:
            relocs.append(20)  # offset 20 = pixel_engine_data_ptr

        return data, relocs

    def _parse_mobj(self, render_mode=0, diffuse=(128, 128, 128, 255),
                    ambient=(64, 64, 64, 255), specular=(255, 255, 255, 255),
                    alpha=1.0, shininess=50.0, pe_data=None):
        """Parse a MaterialObject with linked Material from binary."""
        data, relocs = self._build_mobj_data(
            render_mode=render_mode, diffuse=diffuse, ambient=ambient,
            specular=specular, alpha=alpha, shininess=shininess, pe_data=pe_data,
        )

        from tests.helpers import build_dat_with_sections, build_relocation_table
        dat_bytes = build_dat_with_sections(
            data_section=data,
            relocations=relocs,
            sections=[(0, True)],
            section_names=['mobj'],
        )
        parser = DATParser(io.BytesIO(dat_bytes), {})
        mobj = MaterialObject(0, None)
        mobj.loadFromBinary(parser)
        return mobj

    def test_diffuse_color_is_srgb_normalized(self):
        """Material colors in IR should be sRGB [0-1], not linearized."""
        mobj = self._parse_mobj(
            render_mode=RENDER_DIFFUSE | RENDER_DIFFUSE_MAT,
            diffuse=(200, 100, 50, 255),
        )
        ir = describe_material(mobj)
        assert isinstance(ir, IRMaterial)
        assert abs(ir.diffuse_color[0] - 200 / 255) < 1e-5
        assert abs(ir.diffuse_color[1] - 100 / 255) < 1e-5
        assert abs(ir.diffuse_color[2] - 50 / 255) < 1e-5
        assert abs(ir.diffuse_color[3] - 1.0) < 1e-5

    def test_ambient_color_is_srgb_normalized(self):
        mobj = self._parse_mobj(
            render_mode=RENDER_DIFFUSE | RENDER_DIFFUSE_MAT,
            ambient=(100, 200, 50, 128),
        )
        ir = describe_material(mobj)
        assert abs(ir.ambient_color[0] - 100 / 255) < 1e-5
        assert abs(ir.ambient_color[1] - 200 / 255) < 1e-5
        assert abs(ir.ambient_color[2] - 50 / 255) < 1e-5
        assert abs(ir.ambient_color[3] - 128 / 255) < 1e-5

    def test_specular_color_is_srgb_normalized(self):
        mobj = self._parse_mobj(
            render_mode=RENDER_DIFFUSE | RENDER_DIFFUSE_MAT | RENDER_SPECULAR,
            specular=(128, 64, 32, 255),
        )
        ir = describe_material(mobj)
        assert abs(ir.specular_color[0] - 128 / 255) < 1e-5
        assert abs(ir.specular_color[1] - 64 / 255) < 1e-5
        assert abs(ir.specular_color[2] - 32 / 255) < 1e-5

    def test_black_color(self):
        mobj = self._parse_mobj(
            render_mode=RENDER_DIFFUSE | RENDER_DIFFUSE_MAT,
            diffuse=(0, 0, 0, 255),
        )
        ir = describe_material(mobj)
        assert ir.diffuse_color == (0.0, 0.0, 0.0, 1.0)

    def test_white_color(self):
        mobj = self._parse_mobj(
            render_mode=RENDER_DIFFUSE | RENDER_DIFFUSE_MAT,
            diffuse=(255, 255, 255, 255),
        )
        ir = describe_material(mobj)
        assert ir.diffuse_color == (1.0, 1.0, 1.0, 1.0)

    def test_lighting_model_lit(self):
        mobj = self._parse_mobj(render_mode=RENDER_DIFFUSE | RENDER_DIFFUSE_MAT)
        ir = describe_material(mobj)
        assert ir.lighting == LightingModel.LIT

    def test_lighting_model_unlit(self):
        mobj = self._parse_mobj(render_mode=RENDER_DIFFUSE_VTX)
        ir = describe_material(mobj)
        assert ir.lighting == LightingModel.UNLIT

    def test_color_source_vertex(self):
        mobj = self._parse_mobj(render_mode=RENDER_DIFFUSE | RENDER_DIFFUSE_VTX)
        ir = describe_material(mobj)
        assert ir.color_source == ColorSource.VERTEX

    def test_color_source_both(self):
        mobj = self._parse_mobj(render_mode=RENDER_DIFFUSE | RENDER_DIFFUSE_BOTH)
        ir = describe_material(mobj)
        assert ir.color_source == ColorSource.BOTH

    def test_specular_enabled(self):
        mobj = self._parse_mobj(render_mode=RENDER_DIFFUSE | RENDER_SPECULAR)
        ir = describe_material(mobj)
        assert ir.enable_specular is True

    def test_specular_disabled(self):
        mobj = self._parse_mobj(render_mode=RENDER_DIFFUSE)
        ir = describe_material(mobj)
        assert ir.enable_specular is False

    def test_translucent(self):
        mobj = self._parse_mobj(render_mode=RENDER_DIFFUSE | RENDER_XLU)
        ir = describe_material(mobj)
        assert ir.is_translucent is True

    def test_alpha_and_shininess(self):
        mobj = self._parse_mobj(
            render_mode=RENDER_DIFFUSE,
            alpha=0.75, shininess=25.0,
        )
        ir = describe_material(mobj)
        assert abs(ir.alpha - 0.75) < 1e-5
        assert abs(ir.shininess - 25.0) < 1e-5

    def test_no_textures(self):
        mobj = self._parse_mobj(render_mode=RENDER_DIFFUSE | RENDER_DIFFUSE_MAT)
        ir = describe_material(mobj)
        assert ir.texture_layers == []

    def test_no_pixel_engine(self):
        mobj = self._parse_mobj(render_mode=RENDER_DIFFUSE)
        ir = describe_material(mobj)
        assert ir.fragment_blending is None

    def test_pixel_engine_alpha_blend(self):
        pe = build_pixel_engine(
            pe_type=GX_BM_BLEND,
            source_factor=GX_BL_SRCALPHA,
            destination_factor=GX_BL_INVSRCALPHA,
        )
        mobj = self._parse_mobj(render_mode=RENDER_DIFFUSE, pe_data=pe)
        ir = describe_material(mobj)
        assert ir.fragment_blending is not None
        assert ir.fragment_blending.effect == OutputBlendEffect.ALPHA_BLEND
        assert ir.fragment_blending.source_factor == BlendFactor.SRC_ALPHA
        assert ir.fragment_blending.dest_factor == BlendFactor.INV_SRC_ALPHA

    def test_pixel_engine_additive(self):
        pe = build_pixel_engine(
            pe_type=GX_BM_BLEND,
            source_factor=GX_BL_ONE,
            destination_factor=GX_BL_ONE,
        )
        mobj = self._parse_mobj(render_mode=RENDER_DIFFUSE, pe_data=pe)
        ir = describe_material(mobj)
        assert ir.fragment_blending.effect == OutputBlendEffect.ADDITIVE

    def test_alpha_compat_render_mode(self):
        """RENDER_ALPHA_COMPAT should derive alpha source from diffuse flags."""
        mobj = self._parse_mobj(
            render_mode=RENDER_DIFFUSE | RENDER_DIFFUSE_VTX | RENDER_ALPHA_COMPAT,
        )
        ir = describe_material(mobj)
        # RENDER_ALPHA_COMPAT + RENDER_DIFFUSE_VTX → alpha = VTX << shift
        assert ir.alpha_source == ColorSource.VERTEX
