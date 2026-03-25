"""Describe MaterialObject → IRMaterial with textures and images.

Extracts render_mode flags, material colors, texture chain parameters,
and decoded image pixel data into IR dataclasses without any bpy calls.
"""
try:
    from ....shared.IR.material import (
        IRMaterial, IRTextureLayer, IRImage, FragmentBlending,
        CombinerInput, CombinerStage, ColorCombiner,
    )
    from ....shared.IR.enums import (
        ColorSource, LightingModel, CoordType, WrapMode, TextureInterpolation,
        LayerBlendMode, LightmapChannel, CombinerInputSource, CombinerOp,
        CombinerBias, CombinerScale, OutputBlendEffect, BlendFactor,
    )
    from ....shared.helpers.srgb import srgb_to_linear
    from ....shared.Constants.hsd import *
    from ....shared.Constants.gx import *
except (ImportError, SystemError):
    from shared.IR.material import (
        IRMaterial, IRTextureLayer, IRImage, FragmentBlending,
        CombinerInput, CombinerStage, ColorCombiner,
    )
    from shared.IR.enums import (
        ColorSource, LightingModel, CoordType, WrapMode, TextureInterpolation,
        LayerBlendMode, LightmapChannel, CombinerInputSource, CombinerOp,
        CombinerBias, CombinerScale, OutputBlendEffect, BlendFactor,
    )
    from shared.helpers.srgb import srgb_to_linear
    from shared.Constants.hsd import *
    from shared.Constants.gx import *


def describe_material(mobj, image_cache=None):
    """Extract material data from a MaterialObject node into IRMaterial.

    Args:
        mobj: MaterialObject node from parsed node tree.
        image_cache: dict for deduplicating images by (image_id, palette_id).

    Returns:
        IRMaterial with all fields populated.
    """
    if image_cache is None:
        image_cache = {}

    material = mobj.material
    render_mode = mobj.render_mode

    # Decompose render_mode flags
    diffuse_flags = render_mode & RENDER_DIFFUSE_BITS
    if diffuse_flags == RENDER_DIFFUSE_MAT0:
        diffuse_flags = RENDER_DIFFUSE_MAT

    alpha_flags = render_mode & RENDER_ALPHA_BITS
    if alpha_flags == RENDER_ALPHA_COMPAT:
        alpha_flags = diffuse_flags << RENDER_ALPHA_SHIFT

    # Map to IR enums
    color_source = _map_color_source(diffuse_flags, bool(render_mode & RENDER_DIFFUSE))
    alpha_source = _map_alpha_source(alpha_flags, bool(render_mode & RENDER_DIFFUSE))
    lighting = LightingModel.LIT if render_mode & RENDER_DIFFUSE else LightingModel.UNLIT
    enable_specular = bool(render_mode & RENDER_SPECULAR)
    is_translucent = bool(render_mode & RENDER_XLU)

    # Material colors (linearized from sRGB)
    diffuse_color = _linearize_rgba(material.diffuse.asRGBAList())
    ambient_color = _linearize_rgba(material.ambient.asRGBAList())
    specular_color = _linearize_rgba(material.specular.asRGBAList())

    # Extract enabled textures
    texture_layers = []
    texture = mobj.texture
    texture_number = 0
    while texture:
        if render_mode & (1 << (texture_number + 4)):
            ir_tex = _describe_texture(texture, image_cache)
            if ir_tex is not None:
                texture_layers.append(ir_tex)
        texture = texture.next
        texture_number += 1
        if texture_number > 7:
            break

    # Pixel engine / fragment blending
    fragment_blending = None
    if mobj.pixel_engine_data:
        pe = mobj.pixel_engine_data
        fragment_blending = FragmentBlending(
            effect=_resolve_blend_effect(pe),
            source_factor=_map_blend_factor(pe.source_factor),
            dest_factor=_map_blend_factor(pe.destination_factor),
            alpha_test_threshold_0=pe.alpha_component_0,
            alpha_test_threshold_1=pe.alpha_component_1,
            alpha_test_op=pe.alpha_op,
            depth_compare=pe.z_comp,
        )

    return IRMaterial(
        diffuse_color=diffuse_color,
        ambient_color=ambient_color,
        specular_color=specular_color,
        alpha=material.alpha,
        shininess=material.shininess,
        color_source=color_source,
        alpha_source=alpha_source,
        lighting=lighting,
        enable_specular=enable_specular,
        is_translucent=is_translucent,
        texture_layers=texture_layers,
        fragment_blending=fragment_blending,
    )


def _describe_texture(texture, image_cache):
    """Extract one Texture node into IRTextureLayer."""
    # Get pre-decoded image pixels (decoded during parsing)
    ir_image = None
    if texture.image:
        image_id = texture.image.data_address
        palette_id = texture.palette.address if texture.palette else 0
        cache_key = (image_id, palette_id)

        if cache_key in image_cache:
            ir_image = image_cache[cache_key]
        else:
            ir_image = _build_ir_image(texture)
            if ir_image is not None:
                image_cache[cache_key] = ir_image

    if ir_image is None:
        return None

    # Coordinate type
    coord_mask = texture.flags & TEX_COORD_MASK
    coord_type = _map_coord_type(coord_mask)

    # UV index (source - 4 for 0-based)
    uv_index = max(0, texture.source - 4) if hasattr(texture, 'source') else 0

    # Wrap modes
    wrap_s = _map_wrap_mode(texture.wrap_s)
    wrap_t = _map_wrap_mode(texture.wrap_t)

    # Interpolation from LOD settings
    interpolation = None
    if texture.lod:
        interpolation = _map_interpolation(texture.lod.min_filter)

    # Color and alpha blend modes
    colormap = texture.flags & TEX_COLORMAP_MASK
    alphamap = texture.flags & TEX_ALPHAMAP_MASK
    color_blend = _map_color_blend(colormap)
    alpha_blend = _map_alpha_blend(alphamap)

    # Lightmap channel
    lightmap = texture.flags & TEX_LIGHTMAP_MASK
    lightmap_channel = _map_lightmap_channel(lightmap)

    is_bump = bool(texture.flags & TEX_BUMP)

    # TEV combiner (if present)
    combiner = None
    if texture.tev:
        combiner = _describe_tev(texture.tev)

    return IRTextureLayer(
        image=ir_image,
        coord_type=coord_type,
        uv_index=uv_index,
        rotation=tuple(texture.rotation),
        scale=tuple(texture.scale),
        translation=tuple(texture.translation),
        wrap_s=wrap_s,
        wrap_t=wrap_t,
        repeat_s=texture.repeat_s,
        repeat_t=texture.repeat_t,
        interpolation=interpolation,
        color_blend=color_blend,
        alpha_blend=alpha_blend,
        blend_factor=texture.blending,
        lightmap_channel=lightmap_channel,
        is_bump=is_bump,
        combiner=combiner,
    )


def _build_ir_image(texture):
    """Build an IRImage from a Texture node's pre-decoded pixel data.

    Texture.decoded_pixels is set during Phase 3 (parsing) by
    Image.decodeFromRawData(). The data is already cropped and
    vertically flipped (bottom-to-top, matching Blender convention).

    Stores raw u8 bytes in IRImage.pixels — the float conversion
    happens in Phase 5A when assigning to bpy.data.images.pixels.
    """
    image_node = texture.image
    pixel_data = getattr(texture, 'decoded_pixels', None)

    if pixel_data is None or image_node is None:
        return None

    width = image_node.width
    height = image_node.height

    return IRImage(
        name=f"tex_{image_node.address:X}",
        width=width,
        height=height,
        pixels=bytes(pixel_data),
        image_id=image_node.address,
        palette_id=texture.palette.address if texture.palette else 0,
    )


def _describe_tev(tev):
    """Extract TEV combiner settings into ColorCombiner."""
    color_stage = None
    alpha_stage = None

    if tev.active & TOBJ_TEVREG_ACTIVE_COLOR_TEV:
        color_stage = CombinerStage(
            input_a=_map_tev_color_input(tev.color_a, tev),
            input_b=_map_tev_color_input(tev.color_b, tev),
            input_c=_map_tev_color_input(tev.color_c, tev),
            input_d=_map_tev_color_input(tev.color_d, tev),
            operation=CombinerOp.ADD if tev.color_op == GX_TEV_ADD else CombinerOp.SUBTRACT,
            bias=_map_tev_bias(tev.color_bias),
            scale=_map_tev_scale(tev.color_scale),
            clamp=bool(tev.color_clamp == GX_TRUE),
        )

    if tev.active & TOBJ_TEVREG_ACTIVE_ALPHA_TEV:
        alpha_stage = CombinerStage(
            input_a=_map_tev_alpha_input(tev.alpha_a, tev),
            input_b=_map_tev_alpha_input(tev.alpha_b, tev),
            input_c=_map_tev_alpha_input(tev.alpha_c, tev),
            input_d=_map_tev_alpha_input(tev.alpha_d, tev),
            operation=CombinerOp.ADD if tev.alpha_op == GX_TEV_ADD else CombinerOp.SUBTRACT,
            bias=_map_tev_bias(tev.alpha_bias),
            scale=_map_tev_scale(tev.alpha_scale),
            clamp=bool(tev.alpha_clamp == GX_TRUE),
        )

    if color_stage is None and alpha_stage is None:
        return None

    return ColorCombiner(color=color_stage, alpha=alpha_stage)


# --- Mapping helpers ---

def _linearize_rgba(rgba):
    """Convert sRGB [0-1] RGBA to linear, preserving alpha."""
    return (srgb_to_linear(rgba[0]), srgb_to_linear(rgba[1]),
            srgb_to_linear(rgba[2]), rgba[3])


def _map_color_source(diffuse_flags, render_diffuse):
    if render_diffuse:
        if diffuse_flags == RENDER_DIFFUSE_VTX:
            return ColorSource.VERTEX
        elif diffuse_flags == RENDER_DIFFUSE_BOTH:
            return ColorSource.BOTH
        return ColorSource.MATERIAL
    else:
        if diffuse_flags == RENDER_DIFFUSE_MAT:
            return ColorSource.MATERIAL
        elif diffuse_flags == RENDER_DIFFUSE_VTX:
            return ColorSource.VERTEX
        return ColorSource.BOTH


def _map_alpha_source(alpha_flags, render_diffuse):
    if alpha_flags == RENDER_ALPHA_MAT:
        return ColorSource.MATERIAL
    elif alpha_flags == RENDER_ALPHA_VTX:
        return ColorSource.VERTEX
    elif alpha_flags == RENDER_ALPHA_BOTH:
        return ColorSource.BOTH
    return ColorSource.MATERIAL


def _map_coord_type(coord_mask):
    if coord_mask == TEX_COORD_REFLECTION:
        return CoordType.REFLECTION
    return CoordType.UV


def _map_wrap_mode(gx_wrap):
    if gx_wrap == GX_CLAMP:
        return WrapMode.CLAMP
    elif gx_wrap == GX_MIRROR:
        return WrapMode.MIRROR
    return WrapMode.REPEAT


def _map_interpolation(gx_filter):
    mapping = {
        GX_NEAR: TextureInterpolation.CLOSEST,
        GX_LINEAR: TextureInterpolation.LINEAR,
        GX_NEAR_MIP_NEAR: TextureInterpolation.CLOSEST,
        GX_LIN_MIP_NEAR: TextureInterpolation.LINEAR,
        GX_NEAR_MIP_LIN: TextureInterpolation.CLOSEST,
        GX_LIN_MIP_LIN: TextureInterpolation.CUBIC,
    }
    return mapping.get(gx_filter, TextureInterpolation.LINEAR)


def _map_color_blend(colormap):
    mapping = {
        TEX_COLORMAP_NONE: LayerBlendMode.NONE,
        TEX_COLORMAP_PASS: LayerBlendMode.PASS,
        TEX_COLORMAP_REPLACE: LayerBlendMode.REPLACE,
        TEX_COLORMAP_ALPHA_MASK: LayerBlendMode.ALPHA_MASK,
        TEX_COLORMAP_RGB_MASK: LayerBlendMode.RGB_MASK,
        TEX_COLORMAP_BLEND: LayerBlendMode.MIX,
        TEX_COLORMAP_MODULATE: LayerBlendMode.MULTIPLY,
        TEX_COLORMAP_ADD: LayerBlendMode.ADD,
        TEX_COLORMAP_SUB: LayerBlendMode.SUBTRACT,
    }
    return mapping.get(colormap, LayerBlendMode.NONE)


def _map_alpha_blend(alphamap):
    mapping = {
        TEX_ALPHAMAP_NONE: LayerBlendMode.NONE,
        TEX_ALPHAMAP_PASS: LayerBlendMode.PASS,
        TEX_ALPHAMAP_REPLACE: LayerBlendMode.REPLACE,
        TEX_ALPHAMAP_ALPHA_MASK: LayerBlendMode.ALPHA_MASK,
        TEX_ALPHAMAP_BLEND: LayerBlendMode.MIX,
        TEX_ALPHAMAP_MODULATE: LayerBlendMode.MULTIPLY,
        TEX_ALPHAMAP_ADD: LayerBlendMode.ADD,
        TEX_ALPHAMAP_SUB: LayerBlendMode.SUBTRACT,
    }
    return mapping.get(alphamap, LayerBlendMode.NONE)


def _map_lightmap_channel(lightmap):
    if lightmap & TEX_LIGHTMAP_DIFFUSE:
        return LightmapChannel.DIFFUSE
    elif lightmap & TEX_LIGHTMAP_SPECULAR:
        return LightmapChannel.SPECULAR
    elif lightmap & TEX_LIGHTMAP_AMBIENT:
        return LightmapChannel.AMBIENT
    elif lightmap & TEX_LIGHTMAP_EXT:
        return LightmapChannel.EXTENSION
    return LightmapChannel.NONE


def _resolve_blend_effect(pe):
    """Map pixel engine type + factors to an OutputBlendEffect."""
    if pe.type == GX_BM_NONE:
        return OutputBlendEffect.OPAQUE
    elif pe.type == GX_BM_BLEND:
        sf, df = pe.source_factor, pe.destination_factor
        if sf == GX_BL_SRCALPHA and df == GX_BL_INVSRCALPHA:
            return OutputBlendEffect.ALPHA_BLEND
        elif sf == GX_BL_INVSRCALPHA and df == GX_BL_SRCALPHA:
            return OutputBlendEffect.INVERSE_ALPHA_BLEND
        elif sf == GX_BL_ONE and df == GX_BL_ONE:
            return OutputBlendEffect.ADDITIVE
        elif sf == GX_BL_SRCALPHA and df == GX_BL_ONE:
            return OutputBlendEffect.ADDITIVE_ALPHA
        elif sf == GX_BL_INVSRCALPHA and df == GX_BL_ONE:
            return OutputBlendEffect.ADDITIVE_INV_ALPHA
        elif sf == GX_BL_DSTCLR and df == GX_BL_ZERO:
            return OutputBlendEffect.MULTIPLY
        elif sf == GX_BL_ONE and df == GX_BL_ZERO:
            return OutputBlendEffect.OPAQUE
        elif sf == GX_BL_ZERO and df == GX_BL_ZERO:
            return OutputBlendEffect.BLACK
        elif sf == GX_BL_ZERO and df == GX_BL_ONE:
            return OutputBlendEffect.INVISIBLE
        elif sf == GX_BL_SRCALPHA and df == GX_BL_ZERO:
            return OutputBlendEffect.SRC_ALPHA_ONLY
        elif sf == GX_BL_INVSRCALPHA and df == GX_BL_ZERO:
            return OutputBlendEffect.INV_SRC_ALPHA_ONLY
        return OutputBlendEffect.CUSTOM
    elif pe.type == GX_BM_LOGIC:
        if pe.logic_op == GX_LO_CLEAR:
            return OutputBlendEffect.BLACK
        elif pe.logic_op == GX_LO_SET:
            return OutputBlendEffect.WHITE
        elif pe.logic_op == GX_LO_INVCOPY:
            return OutputBlendEffect.INVERT
        elif pe.logic_op == GX_LO_NOOP:
            return OutputBlendEffect.INVISIBLE
        return OutputBlendEffect.OPAQUE
    elif pe.type == GX_BM_SUBTRACT:
        return OutputBlendEffect.CUSTOM
    return OutputBlendEffect.OPAQUE


def _map_blend_factor(gx_factor):
    mapping = {
        GX_BL_ZERO: BlendFactor.ZERO,
        GX_BL_ONE: BlendFactor.ONE,
        GX_BL_SRCCLR: BlendFactor.SRC_COLOR,
        GX_BL_INVSRCCLR: BlendFactor.INV_SRC_COLOR,
        GX_BL_SRCALPHA: BlendFactor.SRC_ALPHA,
        GX_BL_INVSRCALPHA: BlendFactor.INV_SRC_ALPHA,
        GX_BL_DSTALPHA: BlendFactor.DST_ALPHA,
        GX_BL_INVDSTALPHA: BlendFactor.INV_DST_ALPHA,
        GX_BL_DSTCLR: BlendFactor.SRC_COLOR,  # closest match
    }
    return mapping.get(gx_factor, BlendFactor.ZERO)


# --- TEV input mapping ---

def _map_tev_color_input(flag, tev):
    if flag == GX_CC_ZERO:
        return CombinerInput(source=CombinerInputSource.ZERO)
    elif flag == GX_CC_ONE:
        return CombinerInput(source=CombinerInputSource.ONE)
    elif flag == GX_CC_HALF:
        return CombinerInput(source=CombinerInputSource.HALF)
    elif flag == GX_CC_TEXC:
        return CombinerInput(source=CombinerInputSource.TEXTURE_COLOR)
    elif flag == GX_CC_TEXA:
        return CombinerInput(source=CombinerInputSource.TEXTURE_ALPHA)
    elif flag == TOBJ_TEV_CC_KONST_RGB:
        return CombinerInput(source=CombinerInputSource.CONSTANT, channel="RGB",
                             value=_tev_color_value(tev.konst))
    elif flag == TOBJ_TEV_CC_KONST_RRR:
        return CombinerInput(source=CombinerInputSource.CONSTANT, channel="RRR",
                             value=_tev_color_value(tev.konst))
    elif flag == TOBJ_TEV_CC_KONST_GGG:
        return CombinerInput(source=CombinerInputSource.CONSTANT, channel="GGG",
                             value=_tev_color_value(tev.konst))
    elif flag == TOBJ_TEV_CC_KONST_BBB:
        return CombinerInput(source=CombinerInputSource.CONSTANT, channel="BBB",
                             value=_tev_color_value(tev.konst))
    elif flag == TOBJ_TEV_CC_KONST_AAA:
        return CombinerInput(source=CombinerInputSource.CONSTANT, channel="AAA",
                             value=_tev_color_value(tev.konst))
    elif flag == TOBJ_TEV_CC_TEX0_RGB:
        return CombinerInput(source=CombinerInputSource.REGISTER_0, channel="RGB",
                             value=_tev_color_value(tev.tev0))
    elif flag == TOBJ_TEV_CC_TEX0_AAA:
        return CombinerInput(source=CombinerInputSource.REGISTER_0, channel="AAA",
                             value=_tev_color_value(tev.tev0))
    elif flag == TOBJ_TEV_CC_TEX1_RGB:
        return CombinerInput(source=CombinerInputSource.REGISTER_1, channel="RGB",
                             value=_tev_color_value(tev.tev1))
    elif flag == TOBJ_TEV_CC_TEX1_AAA:
        return CombinerInput(source=CombinerInputSource.REGISTER_1, channel="AAA",
                             value=_tev_color_value(tev.tev1))
    return CombinerInput(source=CombinerInputSource.TEXTURE_COLOR)


def _map_tev_alpha_input(flag, tev):
    if flag == GX_CA_ZERO:
        return CombinerInput(source=CombinerInputSource.ZERO)
    elif flag == GX_CA_TEXA:
        return CombinerInput(source=CombinerInputSource.TEXTURE_ALPHA)
    elif flag == TOBJ_TEV_CA_KONST_R:
        return CombinerInput(source=CombinerInputSource.CONSTANT, channel="R",
                             value=_tev_color_value(tev.konst))
    elif flag == TOBJ_TEV_CA_KONST_G:
        return CombinerInput(source=CombinerInputSource.CONSTANT, channel="G",
                             value=_tev_color_value(tev.konst))
    elif flag == TOBJ_TEV_CA_KONST_B:
        return CombinerInput(source=CombinerInputSource.CONSTANT, channel="B",
                             value=_tev_color_value(tev.konst))
    elif flag == TOBJ_TEV_CA_KONST_A:
        return CombinerInput(source=CombinerInputSource.CONSTANT, channel="A",
                             value=_tev_color_value(tev.konst))
    elif flag == TOBJ_TEV_CA_TEX0_A:
        return CombinerInput(source=CombinerInputSource.REGISTER_0, channel="A",
                             value=_tev_color_value(tev.tev0))
    elif flag == TOBJ_TEV_CA_TEX1_A:
        return CombinerInput(source=CombinerInputSource.REGISTER_1, channel="A",
                             value=_tev_color_value(tev.tev1))
    return CombinerInput(source=CombinerInputSource.TEXTURE_ALPHA)


def _tev_color_value(color_obj):
    """Extract RGBA tuple from a TEV color register object."""
    if hasattr(color_obj, 'red'):
        return (color_obj.red / 255.0, color_obj.green / 255.0,
                color_obj.blue / 255.0, color_obj.alpha / 255.0)
    return (0.0, 0.0, 0.0, 1.0)


def _map_tev_bias(bias):
    if bias == GX_TB_ADDHALF:
        return CombinerBias.PLUS_HALF
    elif bias == GX_TB_SUBHALF:
        return CombinerBias.MINUS_HALF
    return CombinerBias.ZERO


def _map_tev_scale(scale):
    mapping = {
        GX_CS_SCALE_1: CombinerScale.SCALE_1,
        GX_CS_SCALE_2: CombinerScale.SCALE_2,
        GX_CS_SCALE_4: CombinerScale.SCALE_4,
        GX_CS_DIVIDE_2: CombinerScale.SCALE_HALF,
    }
    return mapping.get(scale, CombinerScale.SCALE_1)
