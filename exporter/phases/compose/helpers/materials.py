"""Compose IRMaterial into MaterialObject → Material → Texture node chains.

Reverses importer/phases/describe/helpers/materials.py:describe_material().
Takes IRMaterial dataclasses and reconstructs the SysDolphin node tree
for serialization into a .dat binary.
"""
try:
    from .....shared.Nodes.Classes.Material.MaterialObject import MaterialObject
    from .....shared.Nodes.Classes.Material.Material import Material as MaterialNode
    from .....shared.Nodes.Classes.Texture.Texture import Texture
    from .....shared.Nodes.Classes.Texture.Image import Image
    from .....shared.Nodes.Classes.Texture.Palette import Palette
    from .....shared.Nodes.Classes.Texture.TextureLOD import TextureLOD
    from .....shared.Nodes.Classes.Texture.TextureTEV import TextureTEV
    from .....shared.Nodes.Classes.Rendering.PixelEngine import PixelEngine
    from .....shared.texture_encoder import analyze_pixels, select_format, encode_texture
    from .....shared.Nodes.Classes.Colors.RGBAColor import RGBAColor, RGBX8Color
    from .....shared.Constants.hsd import (
        RENDER_DIFFUSE, RENDER_SPECULAR, RENDER_XLU,
        RENDER_DIFFUSE_MAT, RENDER_DIFFUSE_VTX, RENDER_DIFFUSE_BOTH,
        RENDER_ALPHA_MAT, RENDER_ALPHA_VTX, RENDER_ALPHA_BOTH,
        RENDER_TEX0,
        TEX_COORD_UV, TEX_COORD_REFLECTION,
        TEX_COLORMAP_NONE, TEX_COLORMAP_ALPHA_MASK, TEX_COLORMAP_RGB_MASK,
        TEX_COLORMAP_BLEND, TEX_COLORMAP_MODULATE, TEX_COLORMAP_REPLACE,
        TEX_COLORMAP_PASS, TEX_COLORMAP_ADD, TEX_COLORMAP_SUB,
        TEX_ALPHAMAP_NONE, TEX_ALPHAMAP_ALPHA_MASK, TEX_ALPHAMAP_BLEND,
        TEX_ALPHAMAP_MODULATE, TEX_ALPHAMAP_REPLACE, TEX_ALPHAMAP_PASS,
        TEX_ALPHAMAP_ADD, TEX_ALPHAMAP_SUB,
        TEX_LIGHTMAP_DIFFUSE, TEX_LIGHTMAP_SPECULAR,
        TEX_LIGHTMAP_AMBIENT, TEX_LIGHTMAP_EXT,
        TEX_BUMP,
        TOBJ_TEV_CC_KONST_RGB, TOBJ_TEV_CC_KONST_RRR,
        TOBJ_TEV_CC_KONST_GGG, TOBJ_TEV_CC_KONST_BBB,
        TOBJ_TEV_CC_KONST_AAA,
        TOBJ_TEV_CC_TEX0_RGB, TOBJ_TEV_CC_TEX0_AAA,
        TOBJ_TEV_CC_TEX1_RGB, TOBJ_TEV_CC_TEX1_AAA,
        TOBJ_TEV_CA_KONST_R, TOBJ_TEV_CA_KONST_G,
        TOBJ_TEV_CA_KONST_B, TOBJ_TEV_CA_KONST_A,
        TOBJ_TEV_CA_TEX0_A, TOBJ_TEV_CA_TEX1_A,
        TOBJ_TEVREG_ACTIVE_COLOR_TEV, TOBJ_TEVREG_ACTIVE_ALPHA_TEV,
        TOBJ_TEVREG_ACTIVE_KONST, TOBJ_TEVREG_ACTIVE_TEV0,
        TOBJ_TEVREG_ACTIVE_TEV1,
    )
    from .....shared.Constants.gx import (
        GX_CLAMP, GX_REPEAT, GX_MIRROR,
        GX_BM_NONE, GX_BM_BLEND, GX_BM_LOGIC,
        GX_BL_ZERO, GX_BL_ONE, GX_BL_SRCCLR, GX_BL_INVSRCCLR,
        GX_BL_SRCALPHA, GX_BL_INVSRCALPHA, GX_BL_DSTALPHA, GX_BL_INVDSTALPHA,
        GX_BL_DSTCLR,
        GX_LO_CLEAR, GX_LO_SET, GX_LO_INVCOPY, GX_LO_NOOP, GX_LO_COPY,
        GX_TEV_ADD, GX_TEV_SUB,
        GX_TB_ZERO, GX_TB_ADDHALF, GX_TB_SUBHALF,
        GX_CS_SCALE_1, GX_CS_SCALE_2, GX_CS_SCALE_4, GX_CS_DIVIDE_2,
        GX_CC_ZERO, GX_CC_ONE, GX_CC_HALF, GX_CC_TEXC, GX_CC_TEXA,
        GX_CA_ZERO, GX_CA_TEXA,
        GX_TRUE,
    )
    from .....shared.IR.enums import (
        ColorSource, LightingModel, CoordType, WrapMode,
        LayerBlendMode, LightmapChannel,
        OutputBlendEffect, BlendFactor,
        CombinerInputSource, CombinerOp, CombinerBias, CombinerScale,
    )
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Material.MaterialObject import MaterialObject
    from shared.Nodes.Classes.Material.Material import Material as MaterialNode
    from shared.Nodes.Classes.Texture.Texture import Texture
    from shared.Nodes.Classes.Texture.Image import Image
    from shared.Nodes.Classes.Texture.Palette import Palette
    from shared.Nodes.Classes.Texture.TextureLOD import TextureLOD
    from shared.Nodes.Classes.Texture.TextureTEV import TextureTEV
    from shared.Nodes.Classes.Rendering.PixelEngine import PixelEngine
    from shared.texture_encoder import analyze_pixels, select_format, encode_texture
    from shared.Nodes.Classes.Colors.RGBAColor import RGBAColor, RGBX8Color
    from shared.Constants.hsd import (
        RENDER_DIFFUSE, RENDER_SPECULAR, RENDER_XLU,
        RENDER_DIFFUSE_MAT, RENDER_DIFFUSE_VTX, RENDER_DIFFUSE_BOTH,
        RENDER_ALPHA_MAT, RENDER_ALPHA_VTX, RENDER_ALPHA_BOTH,
        RENDER_TEX0,
        TEX_COORD_UV, TEX_COORD_REFLECTION,
        TEX_COLORMAP_NONE, TEX_COLORMAP_ALPHA_MASK, TEX_COLORMAP_RGB_MASK,
        TEX_COLORMAP_BLEND, TEX_COLORMAP_MODULATE, TEX_COLORMAP_REPLACE,
        TEX_COLORMAP_PASS, TEX_COLORMAP_ADD, TEX_COLORMAP_SUB,
        TEX_ALPHAMAP_NONE, TEX_ALPHAMAP_ALPHA_MASK, TEX_ALPHAMAP_BLEND,
        TEX_ALPHAMAP_MODULATE, TEX_ALPHAMAP_REPLACE, TEX_ALPHAMAP_PASS,
        TEX_ALPHAMAP_ADD, TEX_ALPHAMAP_SUB,
        TEX_LIGHTMAP_DIFFUSE, TEX_LIGHTMAP_SPECULAR,
        TEX_LIGHTMAP_AMBIENT, TEX_LIGHTMAP_EXT,
        TEX_BUMP,
        TOBJ_TEV_CC_KONST_RGB, TOBJ_TEV_CC_KONST_RRR,
        TOBJ_TEV_CC_KONST_GGG, TOBJ_TEV_CC_KONST_BBB,
        TOBJ_TEV_CC_KONST_AAA,
        TOBJ_TEV_CC_TEX0_RGB, TOBJ_TEV_CC_TEX0_AAA,
        TOBJ_TEV_CC_TEX1_RGB, TOBJ_TEV_CC_TEX1_AAA,
        TOBJ_TEV_CA_KONST_R, TOBJ_TEV_CA_KONST_G,
        TOBJ_TEV_CA_KONST_B, TOBJ_TEV_CA_KONST_A,
        TOBJ_TEV_CA_TEX0_A, TOBJ_TEV_CA_TEX1_A,
        TOBJ_TEVREG_ACTIVE_COLOR_TEV, TOBJ_TEVREG_ACTIVE_ALPHA_TEV,
        TOBJ_TEVREG_ACTIVE_KONST, TOBJ_TEVREG_ACTIVE_TEV0,
        TOBJ_TEVREG_ACTIVE_TEV1,
    )
    from shared.Constants.gx import (
        GX_CLAMP, GX_REPEAT, GX_MIRROR,
        GX_BM_NONE, GX_BM_BLEND, GX_BM_LOGIC,
        GX_BL_ZERO, GX_BL_ONE, GX_BL_SRCCLR, GX_BL_INVSRCCLR,
        GX_BL_SRCALPHA, GX_BL_INVSRCALPHA, GX_BL_DSTALPHA, GX_BL_INVDSTALPHA,
        GX_BL_DSTCLR,
        GX_LO_CLEAR, GX_LO_SET, GX_LO_INVCOPY, GX_LO_NOOP, GX_LO_COPY,
        GX_TEV_ADD, GX_TEV_SUB,
        GX_TB_ZERO, GX_TB_ADDHALF, GX_TB_SUBHALF,
        GX_CS_SCALE_1, GX_CS_SCALE_2, GX_CS_SCALE_4, GX_CS_DIVIDE_2,
        GX_CC_ZERO, GX_CC_ONE, GX_CC_HALF, GX_CC_TEXC, GX_CC_TEXA,
        GX_CA_ZERO, GX_CA_TEXA,
        GX_TRUE,
    )
    from shared.IR.enums import (
        ColorSource, LightingModel, CoordType, WrapMode,
        LayerBlendMode, LightmapChannel,
        OutputBlendEffect, BlendFactor,
        CombinerInputSource, CombinerOp, CombinerBias, CombinerScale,
    )
    from shared.helpers.logger import StubLogger


def compose_material(ir_material, logger=StubLogger()):
    """Convert an IRMaterial into a MaterialObject node tree.

    Args:
        ir_material: IRMaterial dataclass.
        logger: Logger instance.

    Returns:
        MaterialObject node, or None if ir_material is None.
    """
    if ir_material is None:
        return None

    # Build render_mode flags
    render_mode = _build_render_mode(ir_material)

    # Build Material color node
    mat_node = _build_material_node(ir_material)

    # Build Texture chain
    tex_root = _build_texture_chain(ir_material.texture_layers, logger)

    # Build pixel engine (fragment blending)
    pe_node = _build_pixel_engine(ir_material.fragment_blending)

    # Build MaterialObject
    mobj = MaterialObject(address=None, blender_obj=None)
    mobj.class_type = None
    mobj.render_mode = render_mode
    mobj.texture = tex_root
    mobj.material = mat_node
    mobj.render_data = None
    mobj.pixel_engine_data = pe_node

    logger.debug("      material: render_mode=%#x, textures=%d, pe=%s",
                 render_mode, len(ir_material.texture_layers),
                 "yes" if pe_node else "no")

    return mobj


# ---------------------------------------------------------------------------
# Render mode flag construction
# ---------------------------------------------------------------------------

def _build_render_mode(ir_mat):
    """Build the render_mode bitfield from IRMaterial properties."""
    mode = 0

    # Diffuse source (bits 0-1)
    if ir_mat.color_source == ColorSource.VERTEX:
        mode |= RENDER_DIFFUSE_VTX
    elif ir_mat.color_source == ColorSource.BOTH:
        mode |= RENDER_DIFFUSE_BOTH
    else:
        mode |= RENDER_DIFFUSE_MAT

    # Diffuse lighting enable (bit 2)
    if ir_mat.lighting == LightingModel.LIT:
        mode |= RENDER_DIFFUSE

    # Specular enable (bit 3)
    if ir_mat.enable_specular:
        mode |= RENDER_SPECULAR

    # Texture enable bits (bits 4-11)
    for i in range(min(8, len(ir_mat.texture_layers))):
        mode |= (RENDER_TEX0 << i)

    # Alpha source (bits 13-14)
    if ir_mat.alpha_source == ColorSource.VERTEX:
        mode |= RENDER_ALPHA_VTX
    elif ir_mat.alpha_source == ColorSource.BOTH:
        mode |= RENDER_ALPHA_BOTH
    else:
        mode |= RENDER_ALPHA_MAT

    # Translucency (bit 30)
    if ir_mat.is_translucent:
        mode |= RENDER_XLU

    return mode


# ---------------------------------------------------------------------------
# Material color node
# ---------------------------------------------------------------------------

def _build_material_node(ir_mat):
    """Create a Material node with ambient/diffuse/specular colors."""
    mat = MaterialNode(address=None, blender_obj=None)

    mat.ambient = _make_rgba_color(ir_mat.ambient_color)
    mat.diffuse = _make_rgba_color(ir_mat.diffuse_color)
    mat.specular = _make_rgba_color(ir_mat.specular_color)
    mat.alpha = ir_mat.alpha
    mat.shininess = ir_mat.shininess

    return mat


def _make_rgba_color(color_tuple):
    """Create an RGBAColor node from a normalized (r, g, b, a) tuple."""
    c = RGBAColor(address=None, blender_obj=None)
    c.red = color_tuple[0]
    c.green = color_tuple[1]
    c.blue = color_tuple[2]
    c.alpha = color_tuple[3] if len(color_tuple) > 3 else 1.0
    return c


# ---------------------------------------------------------------------------
# Texture chain construction
# ---------------------------------------------------------------------------

def _build_texture_chain(texture_layers, logger):
    """Build a linked list of Texture nodes from IRTextureLayer list."""
    if not texture_layers:
        return None

    tex_nodes = []
    for i, layer in enumerate(texture_layers):
        tex = _build_texture_node(layer, i, logger)
        tex_nodes.append(tex)

    # Link via .next
    for i in range(len(tex_nodes) - 1):
        tex_nodes[i].next = tex_nodes[i + 1]

    return tex_nodes[0]


def _build_texture_node(ir_layer, tex_index, logger):
    """Create a Texture node from an IRTextureLayer."""
    tex = Texture(address=None, blender_obj=None)
    tex.name = None
    tex.next = None
    tex.texture_id = tex_index

    # UV source: 4 + uv_index (GX convention)
    tex.source = 4 + ir_layer.uv_index

    # Transform — convert Blender UV convention to GX convention.
    # Blender V origin is bottom, GX V origin is top: v_gx = 1 - scale_v - v_blender
    tex.rotation = list(ir_layer.rotation)
    tex.scale = list(ir_layer.scale)
    tex.translation = [
        ir_layer.translation[0],
        1.0 - ir_layer.scale[1] - ir_layer.translation[1],  # reverse V-flip
        ir_layer.translation[2],
    ]

    # Wrap modes
    tex.wrap_s = _map_wrap_mode_to_gx(ir_layer.wrap_s)
    tex.wrap_t = _map_wrap_mode_to_gx(ir_layer.wrap_t)
    tex.repeat_s = ir_layer.repeat_s
    tex.repeat_t = ir_layer.repeat_t

    # Flags
    tex.flags = _build_texture_flags(ir_layer)
    tex.blending = ir_layer.blend_factor
    tex.mag_filter = 1  # GX_LINEAR

    # Image and palette
    img, encode_result = _build_image_node(ir_layer.image, logger)
    tex.image = img
    if encode_result['palette_data'] is not None:
        pal = Palette(address=None, blender_obj=None)
        pal.format = encode_result['palette_format']
        pal.entry_count = encode_result['palette_count']
        pal.raw_data = encode_result['palette_data']
        pal.data = 0  # Set during write
        pal.table_name = None
        tex.palette = pal
    else:
        tex.palette = None
    tex.lod = None
    tex.tev = _build_tev_node(ir_layer.combiner)

    return tex


def _build_texture_flags(ir_layer):
    """Build the texture flags bitfield from IRTextureLayer properties."""
    flags = 0

    # Coord type (bits 0-3)
    if ir_layer.coord_type == CoordType.REFLECTION:
        flags |= TEX_COORD_REFLECTION
    else:
        flags |= TEX_COORD_UV

    # Lightmap channel (bits 4-8)
    lmc = ir_layer.lightmap_channel
    if lmc == LightmapChannel.DIFFUSE:
        flags |= TEX_LIGHTMAP_DIFFUSE
    elif lmc == LightmapChannel.SPECULAR:
        flags |= TEX_LIGHTMAP_SPECULAR
    elif lmc == LightmapChannel.AMBIENT:
        flags |= TEX_LIGHTMAP_AMBIENT
    elif lmc == LightmapChannel.EXTENSION:
        flags |= TEX_LIGHTMAP_EXT

    # Color blend mode (bits 16-19)
    color_map = {
        LayerBlendMode.NONE: TEX_COLORMAP_NONE,
        LayerBlendMode.ALPHA_MASK: TEX_COLORMAP_ALPHA_MASK,
        LayerBlendMode.RGB_MASK: TEX_COLORMAP_RGB_MASK,
        LayerBlendMode.MIX: TEX_COLORMAP_BLEND,
        LayerBlendMode.MULTIPLY: TEX_COLORMAP_MODULATE,
        LayerBlendMode.REPLACE: TEX_COLORMAP_REPLACE,
        LayerBlendMode.PASS: TEX_COLORMAP_PASS,
        LayerBlendMode.ADD: TEX_COLORMAP_ADD,
        LayerBlendMode.SUBTRACT: TEX_COLORMAP_SUB,
    }
    flags |= color_map.get(ir_layer.color_blend, TEX_COLORMAP_REPLACE)

    # Alpha blend mode (bits 20-23)
    alpha_map = {
        LayerBlendMode.NONE: TEX_ALPHAMAP_NONE,
        LayerBlendMode.ALPHA_MASK: TEX_ALPHAMAP_ALPHA_MASK,
        LayerBlendMode.MIX: TEX_ALPHAMAP_BLEND,
        LayerBlendMode.MULTIPLY: TEX_ALPHAMAP_MODULATE,
        LayerBlendMode.REPLACE: TEX_ALPHAMAP_REPLACE,
        LayerBlendMode.PASS: TEX_ALPHAMAP_PASS,
        LayerBlendMode.ADD: TEX_ALPHAMAP_ADD,
        LayerBlendMode.SUBTRACT: TEX_ALPHAMAP_SUB,
    }
    flags |= alpha_map.get(ir_layer.alpha_blend, TEX_ALPHAMAP_REPLACE)

    # Bump (bit 24)
    if ir_layer.is_bump:
        flags |= TEX_BUMP

    return flags


def _map_wrap_mode_to_gx(wrap):
    """Convert IR WrapMode to GX wrap constant."""
    if wrap == WrapMode.CLAMP:
        return GX_CLAMP
    elif wrap == WrapMode.MIRROR:
        return GX_MIRROR
    return GX_REPEAT


# ---------------------------------------------------------------------------
# Image node construction
# ---------------------------------------------------------------------------

def _build_image_node(ir_image, logger=StubLogger()):
    """Create an Image node from an IRImage.

    Selects the best GX texture format based on pixel content analysis
    (or user override), encodes the pixels, and returns the Image node.
    For palette-indexed formats, also returns palette data.

    Returns:
        (Image node, palette_data dict or None)
    """
    img = Image(address=None, blender_obj=None)
    img.width = ir_image.width
    img.height = ir_image.height
    img.mipmap = 0
    img.minLOD = 0.0
    img.maxLOD = 0.0
    img.data_address = 0  # Set during write

    # Select format and encode
    analysis = analyze_pixels(ir_image.pixels, ir_image.width, ir_image.height)
    format_id = select_format(analysis, ir_image.gx_format_override)
    result = encode_texture(ir_image.pixels, ir_image.width, ir_image.height, format_id)

    img.format = format_id
    img.raw_image_data = result['image_data']

    logger.debug("      image '%s' %dx%d: format=%d, %d bytes",
                 ir_image.name, ir_image.width, ir_image.height,
                 format_id, len(result['image_data']))

    return img, result


# ---------------------------------------------------------------------------
# Pixel engine (fragment blending) construction
# ---------------------------------------------------------------------------

def _build_pixel_engine(fragment_blending):
    """Create a PixelEngine node from an IR FragmentBlending.

    Reverses importer/phases/describe/helpers/materials.py:_resolve_blend_effect()
    and _map_blend_factor(). Fields not stored in the IR (flags, reference_0,
    reference_1, destination_alpha) are set to 0.
    """
    if fragment_blending is None:
        return None

    pe = PixelEngine(address=None, blender_obj=None)

    # Resolve blend type and logic_op from the semantic effect
    blend_type, logic_op = _resolve_blend_type(fragment_blending.effect,
                                               fragment_blending.source_factor,
                                               fragment_blending.dest_factor)

    pe.type = blend_type
    pe.source_factor = _map_blend_factor_to_gx(fragment_blending.source_factor)
    pe.destination_factor = _map_blend_factor_to_gx(fragment_blending.dest_factor)
    pe.logic_op = logic_op

    pe.z_comp = fragment_blending.depth_compare
    pe.alpha_component_0 = fragment_blending.alpha_test_threshold_0
    pe.alpha_op = fragment_blending.alpha_test_op
    pe.alpha_component_1 = fragment_blending.alpha_test_threshold_1

    # Not stored in the IR — use defaults
    pe.flags = 0
    pe.reference_0 = 0
    pe.reference_1 = 0
    pe.destination_alpha = 0

    return pe


def _resolve_blend_type(effect, source_factor, dest_factor):
    """Map an OutputBlendEffect back to (GX blend type, logic_op).

    Inverse of importer's _resolve_blend_effect().
    """
    # Logic-op-only effects
    if effect == OutputBlendEffect.WHITE:
        return GX_BM_LOGIC, GX_LO_SET
    elif effect == OutputBlendEffect.INVERT:
        return GX_BM_LOGIC, GX_LO_INVCOPY

    # OPAQUE: use GX_BM_NONE when factors are trivial, GX_BM_BLEND otherwise
    if effect == OutputBlendEffect.OPAQUE:
        if source_factor == BlendFactor.ONE and dest_factor == BlendFactor.ZERO:
            return GX_BM_BLEND, GX_LO_COPY
        return GX_BM_NONE, 0

    # All remaining effects use GX_BM_BLEND
    return GX_BM_BLEND, GX_LO_COPY


_BLEND_FACTOR_TO_GX = {
    BlendFactor.ZERO: GX_BL_ZERO,
    BlendFactor.ONE: GX_BL_ONE,
    BlendFactor.SRC_COLOR: GX_BL_SRCCLR,
    BlendFactor.INV_SRC_COLOR: GX_BL_INVSRCCLR,
    BlendFactor.SRC_ALPHA: GX_BL_SRCALPHA,
    BlendFactor.INV_SRC_ALPHA: GX_BL_INVSRCALPHA,
    BlendFactor.DST_ALPHA: GX_BL_DSTALPHA,
    BlendFactor.INV_DST_ALPHA: GX_BL_INVDSTALPHA,
}


def _map_blend_factor_to_gx(factor):
    """Convert IR BlendFactor enum to GX_BL_* constant."""
    return _BLEND_FACTOR_TO_GX.get(factor, GX_BL_ZERO)


# ---------------------------------------------------------------------------
# TEV combiner construction
# ---------------------------------------------------------------------------

def _build_tev_node(combiner):
    """Create a TextureTEV node from an IR ColorCombiner.

    Reverses importer/phases/describe/helpers/materials.py:_describe_tev().
    """
    if combiner is None:
        return None

    tev = TextureTEV(address=None, blender_obj=None)

    # Track which register colors are used
    konst_val = (0.0, 0.0, 0.0, 1.0)
    tev0_val = (0.0, 0.0, 0.0, 1.0)
    tev1_val = (0.0, 0.0, 0.0, 1.0)
    active = 0

    if combiner.color:
        stage = combiner.color
        active |= TOBJ_TEVREG_ACTIVE_COLOR_TEV
        tev.color_op = GX_TEV_ADD if stage.operation == CombinerOp.ADD else GX_TEV_SUB
        tev.color_bias = _map_bias_to_gx(stage.bias)
        tev.color_scale = _map_scale_to_gx(stage.scale)
        tev.color_clamp = GX_TRUE if stage.clamp else 0

        tev.color_a, konst_val, tev0_val, tev1_val = _map_color_input_to_gx(
            stage.input_a, konst_val, tev0_val, tev1_val)
        tev.color_b, konst_val, tev0_val, tev1_val = _map_color_input_to_gx(
            stage.input_b, konst_val, tev0_val, tev1_val)
        tev.color_c, konst_val, tev0_val, tev1_val = _map_color_input_to_gx(
            stage.input_c, konst_val, tev0_val, tev1_val)
        tev.color_d, konst_val, tev0_val, tev1_val = _map_color_input_to_gx(
            stage.input_d, konst_val, tev0_val, tev1_val)
    else:
        tev.color_op = GX_TEV_ADD
        tev.color_bias = GX_TB_ZERO
        tev.color_scale = GX_CS_SCALE_1
        tev.color_clamp = GX_TRUE
        tev.color_a = GX_CC_ZERO
        tev.color_b = GX_CC_ZERO
        tev.color_c = GX_CC_ZERO
        tev.color_d = GX_CC_ZERO

    if combiner.alpha:
        stage = combiner.alpha
        active |= TOBJ_TEVREG_ACTIVE_ALPHA_TEV
        tev.alpha_op = GX_TEV_ADD if stage.operation == CombinerOp.ADD else GX_TEV_SUB
        tev.alpha_bias = _map_bias_to_gx(stage.bias)
        tev.alpha_scale = _map_scale_to_gx(stage.scale)
        tev.alpha_clamp = GX_TRUE if stage.clamp else 0

        tev.alpha_a, konst_val, tev0_val, tev1_val = _map_alpha_input_to_gx(
            stage.input_a, konst_val, tev0_val, tev1_val)
        tev.alpha_b, konst_val, tev0_val, tev1_val = _map_alpha_input_to_gx(
            stage.input_b, konst_val, tev0_val, tev1_val)
        tev.alpha_c, konst_val, tev0_val, tev1_val = _map_alpha_input_to_gx(
            stage.input_c, konst_val, tev0_val, tev1_val)
        tev.alpha_d, konst_val, tev0_val, tev1_val = _map_alpha_input_to_gx(
            stage.input_d, konst_val, tev0_val, tev1_val)
    else:
        tev.alpha_op = GX_TEV_ADD
        tev.alpha_bias = GX_TB_ZERO
        tev.alpha_scale = GX_CS_SCALE_1
        tev.alpha_clamp = GX_TRUE
        tev.alpha_a = GX_CA_ZERO
        tev.alpha_b = GX_CA_ZERO
        tev.alpha_c = GX_CA_ZERO
        tev.alpha_d = GX_CA_ZERO

    # Build register color nodes and active mask
    tev.konst = _make_rgbx8_color(konst_val)
    tev.tev0 = _make_rgbx8_color(tev0_val)
    tev.tev1 = _make_rgbx8_color(tev1_val)

    # Set active bits for registers that have non-default values
    if konst_val != (0.0, 0.0, 0.0, 1.0):
        active |= TOBJ_TEVREG_ACTIVE_KONST
    if tev0_val != (0.0, 0.0, 0.0, 1.0):
        active |= TOBJ_TEVREG_ACTIVE_TEV0
    if tev1_val != (0.0, 0.0, 0.0, 1.0):
        active |= TOBJ_TEVREG_ACTIVE_TEV1

    tev.active = active

    return tev


def _make_rgbx8_color(rgba_tuple):
    """Create an RGBX8Color node from a normalized (r, g, b, a) tuple.

    Values are stored as normalized floats [0-1] — writeBinary() converts
    back to u8 automatically.
    """
    c = RGBX8Color(address=None, blender_obj=None)
    c.red = rgba_tuple[0]
    c.green = rgba_tuple[1]
    c.blue = rgba_tuple[2]
    c.alpha = rgba_tuple[3] if len(rgba_tuple) > 3 else 1.0
    c.padding = 0
    return c


def _map_bias_to_gx(bias):
    """Convert IR CombinerBias to GX_TB_* constant."""
    if bias == CombinerBias.PLUS_HALF:
        return GX_TB_ADDHALF
    elif bias == CombinerBias.MINUS_HALF:
        return GX_TB_SUBHALF
    return GX_TB_ZERO


def _map_scale_to_gx(scale):
    """Convert IR CombinerScale to GX_CS_* constant."""
    mapping = {
        CombinerScale.SCALE_1: GX_CS_SCALE_1,
        CombinerScale.SCALE_2: GX_CS_SCALE_2,
        CombinerScale.SCALE_4: GX_CS_SCALE_4,
        CombinerScale.SCALE_HALF: GX_CS_DIVIDE_2,
    }
    return mapping.get(scale, GX_CS_SCALE_1)


# Color input source → GX flag mapping
_COLOR_INPUT_MAP = {
    (CombinerInputSource.ZERO, None): GX_CC_ZERO,
    (CombinerInputSource.ONE, None): GX_CC_ONE,
    (CombinerInputSource.HALF, None): GX_CC_HALF,
    (CombinerInputSource.TEXTURE_COLOR, None): GX_CC_TEXC,
    (CombinerInputSource.TEXTURE_ALPHA, None): GX_CC_TEXA,
    (CombinerInputSource.CONSTANT, "RGB"): TOBJ_TEV_CC_KONST_RGB,
    (CombinerInputSource.CONSTANT, "RRR"): TOBJ_TEV_CC_KONST_RRR,
    (CombinerInputSource.CONSTANT, "GGG"): TOBJ_TEV_CC_KONST_GGG,
    (CombinerInputSource.CONSTANT, "BBB"): TOBJ_TEV_CC_KONST_BBB,
    (CombinerInputSource.CONSTANT, "AAA"): TOBJ_TEV_CC_KONST_AAA,
    (CombinerInputSource.REGISTER_0, "RGB"): TOBJ_TEV_CC_TEX0_RGB,
    (CombinerInputSource.REGISTER_0, "AAA"): TOBJ_TEV_CC_TEX0_AAA,
    (CombinerInputSource.REGISTER_1, "RGB"): TOBJ_TEV_CC_TEX1_RGB,
    (CombinerInputSource.REGISTER_1, "AAA"): TOBJ_TEV_CC_TEX1_AAA,
}

# Alpha input source → GX flag mapping
_ALPHA_INPUT_MAP = {
    (CombinerInputSource.ZERO, None): GX_CA_ZERO,
    (CombinerInputSource.TEXTURE_ALPHA, None): GX_CA_TEXA,
    (CombinerInputSource.CONSTANT, "R"): TOBJ_TEV_CA_KONST_R,
    (CombinerInputSource.CONSTANT, "G"): TOBJ_TEV_CA_KONST_G,
    (CombinerInputSource.CONSTANT, "B"): TOBJ_TEV_CA_KONST_B,
    (CombinerInputSource.CONSTANT, "A"): TOBJ_TEV_CA_KONST_A,
    (CombinerInputSource.REGISTER_0, "A"): TOBJ_TEV_CA_TEX0_A,
    (CombinerInputSource.REGISTER_1, "A"): TOBJ_TEV_CA_TEX1_A,
}


def _map_color_input_to_gx(ci, konst_val, tev0_val, tev1_val):
    """Map a CombinerInput to a GX color input flag and update register values.

    Returns (flag, konst_val, tev0_val, tev1_val).
    """
    flag = _COLOR_INPUT_MAP.get((ci.source, ci.channel), GX_CC_TEXC)

    # Capture register values from the IR input
    if ci.value is not None:
        if ci.source == CombinerInputSource.CONSTANT:
            konst_val = ci.value
        elif ci.source == CombinerInputSource.REGISTER_0:
            tev0_val = ci.value
        elif ci.source == CombinerInputSource.REGISTER_1:
            tev1_val = ci.value

    return flag, konst_val, tev0_val, tev1_val


def _map_alpha_input_to_gx(ci, konst_val, tev0_val, tev1_val):
    """Map a CombinerInput to a GX alpha input flag and update register values.

    Returns (flag, konst_val, tev0_val, tev1_val).
    """
    flag = _ALPHA_INPUT_MAP.get((ci.source, ci.channel), GX_CA_TEXA)

    if ci.value is not None:
        if ci.source == CombinerInputSource.CONSTANT:
            konst_val = ci.value
        elif ci.source == CombinerInputSource.REGISTER_0:
            tev0_val = ci.value
        elif ci.source == CombinerInputSource.REGISTER_1:
            tev1_val = ci.value

    return flag, konst_val, tev0_val, tev1_val
