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
    from .....shared.texture_encoder import analyze_pixels, select_format, encode_texture
    from .....shared.Nodes.Classes.Colors.RGBAColor import RGBAColor
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
    )
    from .....shared.Constants.gx import GX_CLAMP, GX_REPEAT, GX_MIRROR
    from .....shared.IR.enums import (
        ColorSource, LightingModel, CoordType, WrapMode,
        LayerBlendMode, LightmapChannel,
    )
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Material.MaterialObject import MaterialObject
    from shared.Nodes.Classes.Material.Material import Material as MaterialNode
    from shared.Nodes.Classes.Texture.Texture import Texture
    from shared.Nodes.Classes.Texture.Image import Image
    from shared.Nodes.Classes.Texture.Palette import Palette
    from shared.Nodes.Classes.Texture.TextureLOD import TextureLOD
    from shared.texture_encoder import analyze_pixels, select_format, encode_texture
    from shared.Nodes.Classes.Colors.RGBAColor import RGBAColor
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
    )
    from shared.Constants.gx import GX_CLAMP, GX_REPEAT, GX_MIRROR
    from shared.IR.enums import (
        ColorSource, LightingModel, CoordType, WrapMode,
        LayerBlendMode, LightmapChannel,
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

    # Build MaterialObject
    mobj = MaterialObject(address=None, blender_obj=None)
    mobj.class_type = None
    mobj.render_mode = render_mode
    mobj.texture = tex_root
    mobj.material = mat_node
    mobj.render_data = None
    mobj.pixel_engine_data = None

    logger.debug("      material: render_mode=%#x, textures=%d",
                 render_mode, len(ir_material.texture_layers))

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
    tex.tev = None

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
