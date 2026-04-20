"""Describe Blender materials as IRMaterial dataclasses.

Reads material shader node trees and extracts color, texture, and
blending properties back into IR format. Reverses the build_material()
function from importer/phases/build_blender/helpers/materials.py.
"""
import bpy

try:
    from .....shared.IR.material import (
        IRMaterial, IRTextureLayer, IRImage,
    )
    from .....shared.IR.enums import (
        ColorSource, LightingModel, CoordType, WrapMode,
        TextureInterpolation, LayerBlendMode, LightmapChannel,
    )
    from .....shared.helpers.srgb import linear_to_srgb, srgb_to_linear
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.material import (
        IRMaterial, IRTextureLayer, IRImage,
    )
    from shared.IR.enums import (
        ColorSource, LightingModel, CoordType, WrapMode,
        TextureInterpolation, LayerBlendMode, LightmapChannel,
    )
    from shared.helpers.srgb import linear_to_srgb, srgb_to_linear
    from shared.helpers.logger import StubLogger


def describe_material(blender_mat, logger=StubLogger(), cache=None, image_cache=None):
    """Read a Blender material and produce an IRMaterial.

    Extracts properties from the shader node tree, reversing the
    node construction done by build_material().

    Args:
        blender_mat: bpy.types.Material with use_nodes=True.
        logger: Logger instance.
        cache: optional dict keyed on id(blender_mat) → IRMaterial. When
            provided, repeated calls with the same material return the same
            IRMaterial instance — downstream compose/serialize dedup then
            collapses all DObjects sharing that material to a single MObject
            subtree.
        image_cache: optional dict keyed on id(bpy_image) → IRImage, passed
            through to texture extraction to share IRImage instances across
            materials that reuse the same source image.

    Returns:
        IRMaterial, or None if the material has no node tree.
    """
    if not blender_mat or not blender_mat.use_nodes:
        return None

    if cache is not None:
        cached = cache.get(id(blender_mat))
        if cached is not None:
            return cached

    nodes = blender_mat.node_tree.nodes
    links = blender_mat.node_tree.links

    # Find output shader (Principled BSDF or Emission)
    principled = _find_node(nodes, 'ShaderNodeBsdfPrincipled')
    emission = _find_node(nodes, 'ShaderNodeEmission')

    # Determine lighting model
    lighting = LightingModel.UNLIT if (emission and not principled) else LightingModel.LIT

    # Extract diffuse color from RGB nodes or Principled BSDF
    diffuse_color = _extract_rgb_node_color(nodes, links, 'diffuse') or (0.7, 0.7, 0.7, 1.0)
    if principled and diffuse_color == (0.7, 0.7, 0.7, 1.0):
        base_color = principled.inputs['Base Color'].default_value
        diffuse_color = _linear_to_srgb_rgba(base_color)

    # Extract ambient color from the dat_ambient_emission node
    ambient_color = (0.5, 0.5, 0.5, 1.0)
    ambient_node = None
    for node in nodes:
        if node.name == 'dat_ambient_emission':
            ambient_node = node
            break
    if ambient_node:
        amb_linear = ambient_node.inputs['Color'].default_value
        ambient_color = _linear_to_srgb_rgba(amb_linear)

    # Extract specular color from Specular Tint + diffuse color.
    # Blender: specular = mix(white, base, tint) = 1 + tint*(base-1)
    # Reverse: specular_color = 1 + tint * (diffuse - 1)
    specular_color = (1.0, 1.0, 1.0, 1.0)
    if principled and 'Specular Tint' in principled.inputs:
        tint = principled.inputs['Specular Tint'].default_value
        if hasattr(tint, '__len__') and len(tint) >= 3:
            spec = [0.0, 0.0, 0.0, 1.0]
            for c in range(3):
                diff_linear = srgb_to_linear(diffuse_color[c])
                spec_linear = 1.0 + tint[c] * (diff_linear - 1.0)
                spec[c] = linear_to_srgb(max(0.0, min(1.0, spec_linear)))
            specular_color = tuple(spec)

    # Alpha
    alpha = 1.0
    if principled and 'Alpha' in principled.inputs:
        alpha = principled.inputs['Alpha'].default_value

    # Shininess — read the Specular IOR Level and convert back.
    # The importer writes shininess/50 when specular is enabled, 0 when disabled.
    # We store the raw value: if the shader has 0, default to 50.0 (the IR default)
    # since the original shininess is lost when specular is disabled.
    shininess = 50.0
    enable_specular = False
    if principled and 'Specular IOR Level' in principled.inputs:
        spec_val = principled.inputs['Specular IOR Level'].default_value
        if spec_val > 0.001:
            shininess = spec_val * 50.0
            enable_specular = True

    # Color/alpha source detection
    color_source, alpha_source = _detect_color_sources(nodes, links)

    # Texture layers
    texture_layers = _extract_texture_layers(nodes, links, logger, image_cache)

    # Translucency is treated as an UNSUPPORTED feature — materials always
    # ship opaque regardless of the BSDF alpha slider or the texture's
    # alpha channel. Textures can still carry alpha for alpha-test cutouts
    # (that's a texture-format concern, not a material-render-mode one).
    # See documentation/implementation_notes.md (Material translucency is
    # unsupported) for the rationale.
    is_translucent = False

    ir_material = IRMaterial(
        diffuse_color=diffuse_color,
        ambient_color=ambient_color,
        specular_color=specular_color,
        alpha=alpha,
        shininess=shininess,
        color_source=color_source,
        alpha_source=alpha_source,
        lighting=lighting,
        enable_specular=enable_specular,
        is_translucent=is_translucent,
        texture_layers=texture_layers,
    )

    logger.debug("    material '%s': diffuse=%s alpha=%.2f shininess=%.1f lighting=%s textures=%d",
                 blender_mat.name, diffuse_color, alpha, shininess, lighting.value, len(texture_layers))

    if cache is not None:
        cache[id(blender_mat)] = ir_material

    return ir_material


# ---------------------------------------------------------------------------
# Node tree traversal helpers
# ---------------------------------------------------------------------------

def _find_node(nodes, node_type):
    """Find the first node of the given type, skipping shiny filter nodes."""
    for node in nodes:
        if node.bl_idname == node_type:
            if node.name in ('shiny_route_shader', 'shiny_route_mix',
                             'shiny_bright_shader', 'shiny_bright_mix',
                             'dat_ambient_emission', 'dat_ambient_add'):
                continue
            return node
    return None


def _find_nodes(nodes, node_type):
    """Find all nodes of the given type, skipping shiny filter nodes."""
    result = []
    for node in nodes:
        if node.bl_idname == node_type:
            if node.name in ('shiny_route_shader', 'shiny_route_mix',
                             'shiny_bright_shader', 'shiny_bright_mix',
                             'dat_ambient_emission', 'dat_ambient_add'):
                continue
            result.append(node)
    return result


def _extract_rgb_node_color(nodes, links, hint):
    """Find an ShaderNodeRGB and extract its sRGB color.

    The import phase creates RGB nodes for diffuse/ambient/specular.
    We identify them by tracing connections or by position hints.
    """
    rgb_nodes = _find_nodes(nodes, 'ShaderNodeRGB')
    if not rgb_nodes:
        return None

    # If there's only one RGB node, use it as diffuse
    if len(rgb_nodes) == 1 and hint == 'diffuse':
        val = rgb_nodes[0].outputs[0].default_value
        return _linear_to_srgb_rgba(val)

    # For multiple RGB nodes, try to match by what they connect to
    for rgb in rgb_nodes:
        for link in links:
            if link.from_node == rgb:
                to_name = link.to_socket.name.lower() if link.to_socket else ''
                if hint in to_name:
                    val = rgb.outputs[0].default_value
                    return _linear_to_srgb_rgba(val)

    # Fallback: return first for diffuse, second for ambient, third for specular
    idx = {'diffuse': 0, 'ambient': 1, 'specular': 2}.get(hint, 0)
    if idx < len(rgb_nodes):
        val = rgb_nodes[idx].outputs[0].default_value
        return _linear_to_srgb_rgba(val)

    return None


def _linear_to_srgb_rgba(color):
    """Convert a Blender linear RGBA to sRGB RGBA for IR storage."""
    return (
        linear_to_srgb(color[0]),
        linear_to_srgb(color[1]),
        linear_to_srgb(color[2]),
        color[3],
    )


def _detect_color_sources(nodes, links):
    """Detect whether colors come from material, vertex colors, or both."""
    has_vertex_color = False
    has_vertex_alpha = False

    for node in nodes:
        if node.bl_idname == 'ShaderNodeAttribute':
            if node.attribute_name == 'color_0':
                has_vertex_color = True
            elif node.attribute_name == 'alpha_0':
                has_vertex_alpha = True

    if has_vertex_color:
        # Check if there's also a material color (RGB node)
        rgb_nodes = _find_nodes(nodes, 'ShaderNodeRGB')
        color_source = ColorSource.BOTH if rgb_nodes else ColorSource.VERTEX
    else:
        color_source = ColorSource.MATERIAL

    if has_vertex_alpha:
        alpha_source = ColorSource.BOTH if has_vertex_color else ColorSource.VERTEX
    else:
        alpha_source = ColorSource.MATERIAL

    return color_source, alpha_source


def _extract_texture_layers(nodes, links, logger, image_cache=None):
    """Extract texture layers from ShaderNodeTexImage nodes."""
    tex_nodes = _find_nodes(nodes, 'ShaderNodeTexImage')
    layers = []

    for tex_node in tex_nodes:
        layer = _describe_texture_node(tex_node, nodes, links, logger, image_cache)
        if layer is not None:
            layers.append(layer)

    return layers


def _describe_texture_node(tex_node, nodes, links, logger, image_cache=None):
    """Extract an IRTextureLayer from a ShaderNodeTexImage and its connections."""
    image = tex_node.image
    if image is None:
        return None

    # Extract image pixels (shared across materials when image_cache is provided)
    ir_image = _extract_image(image, image_cache)

    # Determine coord type and UV index
    coord_type = CoordType.UV
    uv_index = 0
    mapping_node = None

    # Trace backward from tex_node's Vector input
    for link in links:
        if link.to_node == tex_node and link.to_socket.name == 'Vector':
            source = link.from_node
            if source.bl_idname == 'ShaderNodeMapping':
                mapping_node = source
            elif source.bl_idname == 'ShaderNodeVectorMath':
                # Repeat scaling → trace further back
                for link2 in links:
                    if link2.to_node == source:
                        if link2.from_node.bl_idname == 'ShaderNodeMapping':
                            mapping_node = link2.from_node
            break

    # Find UV map node connected to the mapping
    if mapping_node:
        for link in links:
            if link.to_node == mapping_node:
                if link.from_node.bl_idname == 'ShaderNodeUVMap':
                    uv_name = link.from_node.uv_map
                    # Extract UV index from name like 'uvtex_0'
                    import re
                    match = re.search(r'(\d+)$', uv_name)
                    uv_index = int(match.group(1)) if match else 0
                elif link.from_node.bl_idname == 'ShaderNodeTexCoord':
                    if link.from_socket.name == 'Reflection':
                        coord_type = CoordType.REFLECTION

    # Extract transform from mapping node
    rotation = (0.0, 0.0, 0.0)
    scale = (1.0, 1.0, 1.0)
    translation = (0.0, 0.0, 0.0)
    if mapping_node:
        rot = mapping_node.inputs['Rotation'].default_value
        scl = mapping_node.inputs['Scale'].default_value
        loc = mapping_node.inputs['Location'].default_value
        rotation = (rot[0], rot[1], rot[2])
        scale = (scl[0], scl[1], scl[2])
        translation = (loc[0], loc[1], loc[2])

    # Detect repeat from VectorMath MULTIPLY
    repeat_s = 1
    repeat_t = 1
    for link in links:
        if link.to_node == tex_node and link.to_socket.name == 'Vector':
            if link.from_node.bl_idname == 'ShaderNodeVectorMath':
                vec_math = link.from_node
                if vec_math.operation == 'MULTIPLY':
                    scale_input = vec_math.inputs[1].default_value
                    repeat_s = max(1, int(round(scale_input[0])))
                    repeat_t = max(1, int(round(scale_input[1])))

    # Wrap mode from texture extension
    wrap_map = {
        'REPEAT': WrapMode.REPEAT,
        'EXTEND': WrapMode.CLAMP,
        'CLIP': WrapMode.CLAMP,
        'MIRROR': WrapMode.MIRROR,
    }
    ext = tex_node.extension if hasattr(tex_node, 'extension') else 'REPEAT'
    wrap = wrap_map.get(ext, WrapMode.REPEAT)

    # Interpolation — None means no LOD node (the original default).
    # Only set a value if the texture uses a non-default interpolation.
    interp_map = {
        'Closest': TextureInterpolation.CLOSEST,
        'Cubic': TextureInterpolation.CUBIC,
    }
    interpolation = interp_map.get(tex_node.interpolation, None)

    # Detect blend mode and bump by tracing the texture's Color output
    color_blend, blend_factor, is_bump = _detect_blend_mode(tex_node, links)

    return IRTextureLayer(
        image=ir_image,
        coord_type=coord_type,
        uv_index=uv_index,
        rotation=rotation,
        scale=scale,
        translation=translation,
        wrap_s=wrap,
        wrap_t=wrap,
        repeat_s=repeat_s,
        repeat_t=repeat_t,
        interpolation=interpolation,
        color_blend=color_blend,
        alpha_blend=LayerBlendMode.NONE,
        blend_factor=blend_factor,
        lightmap_channel=LightmapChannel.DIFFUSE,
        is_bump=is_bump,
    )


def _detect_blend_mode(tex_node, links):
    """Detect the color blend mode and bump flag by tracing the texture's output.

    The importer builds the blend stage as a ShaderNodeMixRGB where:
      - Color1 (input 1) = previous layer's output
      - Color2 (input 2) = this texture's Color output
      - Fac   (input 0) = constant (plain MIX), this tex's Alpha (ALPHA_MASK),
                          or this tex's Color (RGB_MASK)
    So ALPHA_MASK and RGB_MASK distinguish themselves from plain MIX by
    having the texture's own Alpha or Color linked into the Fac socket.

    Returns:
        (LayerBlendMode, blend_factor, is_bump)
    """
    blend_type_map = {
        'MIX': LayerBlendMode.MIX,
        'MULTIPLY': LayerBlendMode.MULTIPLY,
        'ADD': LayerBlendMode.ADD,
        'SUBTRACT': LayerBlendMode.SUBTRACT,
    }

    for link in links:
        if link.from_node == tex_node and link.from_socket.name == 'Color':
            target = link.to_node
            if target.bl_idname == 'ShaderNodeMixRGB':
                # Inspect what feeds the Fac socket — this disambiguates
                # ALPHA_MASK / RGB_MASK from a plain blend.
                fac_link = next(
                    (l for l in links
                     if l.to_node == target and l.to_socket == target.inputs[0]),
                    None)
                if fac_link is not None and fac_link.from_node == tex_node:
                    if fac_link.from_socket.name == 'Alpha':
                        return LayerBlendMode.ALPHA_MASK, 1.0, False
                    if fac_link.from_socket.name == 'Color':
                        return LayerBlendMode.RGB_MASK, 1.0, False
                blend_type = blend_type_map.get(target.blend_type, LayerBlendMode.REPLACE)
                factor = target.inputs[0].default_value
                return blend_type, factor, False
            if target.bl_idname == 'ShaderNodeBump':
                return LayerBlendMode.MIX, 0.0, True
            # Direct connection to a shader input → REPLACE
            return LayerBlendMode.REPLACE, 1.0, False

    return LayerBlendMode.REPLACE, 1.0, False


def _extract_image(bpy_image, cache=None):
    """Extract an IRImage from a Blender image.

    When cache is provided, the same bpy.types.Image (by id) produces a
    single shared IRImage instance — downstream compose/serialize dedup
    then collapses duplicate Image nodes and their pixel data.
    """
    if cache is not None:
        cached = cache.get(id(bpy_image))
        if cached is not None:
            return cached

    width = bpy_image.size[0]
    height = bpy_image.size[1]

    # Read pixels as flat RGBA float list, convert to u8 bytes
    pixel_count = width * height
    if pixel_count == 0:
        pixels = b''
    else:
        flat = list(bpy_image.pixels)
        pixel_bytes = bytearray(pixel_count * 4)
        for i in range(pixel_count * 4):
            pixel_bytes[i] = min(255, max(0, int(flat[i] * 255 + 0.5)))
        pixels = bytes(pixel_bytes)

    # Read user's GX format override if the property exists
    try:
        from .....shared.IR.enums import GXTextureFormat
    except (ImportError, SystemError):
        from shared.IR.enums import GXTextureFormat
    gx_format = GXTextureFormat.AUTO
    format_str = getattr(bpy_image, 'dat_gx_format', 'AUTO')
    try:
        gx_format = GXTextureFormat(format_str)
    except (ValueError, KeyError):
        pass

    ir_image = IRImage(
        name=bpy_image.name,
        width=width,
        height=height,
        pixels=pixels,
        image_id=0,
        palette_id=0,
        gx_format_override=gx_format,
    )

    if cache is not None:
        cache[id(bpy_image)] = ir_image

    return ir_image
