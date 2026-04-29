"""Blender shader-graph → IRMaterial decoder.

Reads a `bpy.types.Material` node tree and produces an IRMaterial.
Reverses ``importer/phases/build_blender/helpers/materials.py``.

Used as the deep-work backend for ``describe/helpers/materials.py`` —
the BR shell wraps the IRMaterial returned here while the BR↔IR
distinction for shader graphs is still under-specified. A future pass
can faithfully serialise the node tree into ``BRNodeGraph`` and move
the decoding logic into ``plan/helpers/materials.py``.
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

    principled = _find_node(nodes, 'ShaderNodeBsdfPrincipled')
    emission = _find_node(nodes, 'ShaderNodeEmission')

    def _bsdf_is_dead(p):
        if p is None: return False
        base = None; spec = None
        for inp in p.inputs:
            if inp.name == 'Base Color': base = inp
            elif inp.name == 'Specular IOR Level' or inp.name == 'Specular': spec = inp
        if base is None or base.is_linked:
            return False
        bc = base.default_value
        if bc[0] > 0.01 or bc[1] > 0.01 or bc[2] > 0.01:
            return False
        return True

    if principled is None and emission is not None:
        lighting = LightingModel.UNLIT
    elif principled is not None and emission is not None and _bsdf_is_dead(principled):
        lighting = LightingModel.UNLIT
    else:
        lighting = LightingModel.LIT

    diffuse_color = _extract_rgb_node_color(nodes, links, 'diffuse') or (0.7, 0.7, 0.7, 1.0)
    if principled and diffuse_color == (0.7, 0.7, 0.7, 1.0):
        base_color = principled.inputs['Base Color'].default_value
        diffuse_color = _linear_to_srgb_rgba(base_color)

    ambient_color = (0.5, 0.5, 0.5, 1.0)
    ambient_node = None
    for node in nodes:
        if node.name == 'dat_ambient_emission':
            ambient_node = node
            break
    if ambient_node:
        amb_linear = ambient_node.inputs['Color'].default_value
        ambient_color = _linear_to_srgb_rgba(amb_linear)

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

    alpha = 1.0
    if principled and 'Alpha' in principled.inputs:
        alpha = principled.inputs['Alpha'].default_value

    shininess = 50.0
    enable_specular = False
    if principled and 'Specular IOR Level' in principled.inputs:
        spec_val = principled.inputs['Specular IOR Level'].default_value
        if spec_val > 0.001:
            shininess = spec_val * 50.0
            enable_specular = True

    color_source, alpha_source = _detect_color_sources(nodes, links)
    texture_layers = _extract_texture_layers(nodes, links, logger, image_cache)

    is_translucent = False
    if any(n.type == 'BSDF_TRANSPARENT' for n in nodes):
        is_translucent = True
    elif principled and 'Alpha' in principled.inputs and principled.inputs['Alpha'].is_linked:
        is_translucent = _alpha_wire_has_transparency(
            principled.inputs['Alpha'], threshold=0.5
        )

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


def _find_node(nodes, node_type):
    for node in nodes:
        if node.bl_idname == node_type:
            if node.name in ('shiny_route_shader', 'shiny_route_mix',
                             'shiny_bright_shader', 'shiny_bright_mix',
                             'dat_ambient_emission', 'dat_ambient_add'):
                continue
            return node
    return None


def _detect_per_axis_wrap(tex_node, links):
    vec_input = tex_node.inputs.get('Vector') if hasattr(tex_node.inputs, 'get') else None
    if vec_input is None:
        for inp in tex_node.inputs:
            if inp.name == 'Vector':
                vec_input = inp; break
    if vec_input is None or not vec_input.is_linked:
        return None, None

    combine = vec_input.links[0].from_node
    if combine.bl_idname != 'ShaderNodeCombineXYZ':
        return None, None

    def _trace_axis(axis):
        ax_socket = combine.inputs[axis]
        if not ax_socket.is_linked:
            return None
        op_node = ax_socket.links[0].from_node
        if op_node.bl_idname == 'ShaderNodeMath' and op_node.operation == 'MINIMUM':
            upstream = op_node.inputs[0]
            if upstream.is_linked:
                up = upstream.links[0].from_node
                if (up.bl_idname == 'ShaderNodeMath'
                        and up.operation == 'MAXIMUM'):
                    return WrapMode.CLAMP
            return None
        if op_node.bl_idname == 'ShaderNodeMath' and op_node.operation == 'FRACT':
            return WrapMode.REPEAT
        if op_node.bl_idname == 'ShaderNodeMath' and op_node.operation == 'PINGPONG':
            return WrapMode.MIRROR
        return None

    return _trace_axis(0), _trace_axis(1)


def _alpha_wire_has_transparency(alpha_input, threshold=0.5, sample_count=1024):
    if not alpha_input.is_linked:
        return alpha_input.default_value < threshold
    visited = set()
    stack = [link.from_node for link in alpha_input.links]
    while stack:
        node = stack.pop()
        if node is None or id(node) in visited:
            continue
        visited.add(id(node))
        if node.bl_idname == 'ShaderNodeTexImage':
            img = node.image
            if img and img.has_data and img.channels >= 4:
                n_px = len(img.pixels) // img.channels
                if n_px > 0:
                    step = max(1, n_px // sample_count)
                    for i in range(0, n_px, step):
                        if img.pixels[i * img.channels + 3] < threshold:
                            return True
        for inp in getattr(node, 'inputs', ()):
            for link in getattr(inp, 'links', ()):
                stack.append(link.from_node)
    return False


def _find_nodes(nodes, node_type):
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
    rgb_nodes = _find_nodes(nodes, 'ShaderNodeRGB')
    if not rgb_nodes:
        return None
    if len(rgb_nodes) == 1 and hint == 'diffuse':
        val = rgb_nodes[0].outputs[0].default_value
        return _linear_to_srgb_rgba(val)
    for rgb in rgb_nodes:
        for link in links:
            if link.from_node == rgb:
                to_name = link.to_socket.name.lower() if link.to_socket else ''
                if hint in to_name:
                    val = rgb.outputs[0].default_value
                    return _linear_to_srgb_rgba(val)
    idx = {'diffuse': 0, 'ambient': 1, 'specular': 2}.get(hint, 0)
    if idx < len(rgb_nodes):
        val = rgb_nodes[idx].outputs[0].default_value
        return _linear_to_srgb_rgba(val)
    return None


def _linear_to_srgb_rgba(color):
    return (
        linear_to_srgb(color[0]),
        linear_to_srgb(color[1]),
        linear_to_srgb(color[2]),
        color[3],
    )


def _detect_color_sources(nodes, links):
    has_vertex_color = False
    has_vertex_alpha = False
    for node in nodes:
        if node.bl_idname == 'ShaderNodeAttribute':
            if node.attribute_name == 'color_0':
                has_vertex_color = True
            elif node.attribute_name == 'alpha_0':
                has_vertex_alpha = True
    if has_vertex_color:
        rgb_nodes = _find_nodes(nodes, 'ShaderNodeRGB')
        color_source = ColorSource.BOTH if rgb_nodes else ColorSource.VERTEX
    else:
        color_source = ColorSource.MATERIAL
    if has_vertex_alpha:
        alpha_source = ColorSource.BOTH if has_vertex_color else ColorSource.VERTEX
    else:
        alpha_source = ColorSource.MATERIAL
    return color_source, alpha_source


def _order_texture_nodes(tex_nodes, links):
    """Sort ShaderNodeTexImage nodes into layer order (layer 0 = first,
    N = last). Two signals, in priority:
    1. UV-map trailing digit on the upstream UVMap node (e.g. uvtex_3).
    2. Downstream MixRGB chain depth (fallback for REFLECTION-coord layers).
    Ties broken by node name for stability.
    """
    import re

    def _uv_trailing_digit(tex):
        start = None
        for link in links:
            if link.to_node == tex and link.to_socket.name == 'Vector':
                start = link.from_node; break
        if start is None:
            return None
        visited = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            key = cur.name
            if key in visited:
                continue
            visited.add(key)
            if cur.bl_idname == 'ShaderNodeUVMap':
                m = re.search(r'(\d+)$', cur.uv_map or '')
                return int(m.group(1)) if m else None
            for l2 in links:
                if l2.to_node == cur:
                    stack.append(l2.from_node)
        return None

    def _downstream_mix_depth(tex):
        depth = 0
        cur = tex
        visited = set()
        while True:
            key = cur.name
            if key in visited:
                break
            visited.add(key)
            next_mix = None
            for link in links:
                if link.from_node == cur and link.from_socket.name in ('Color', 'Result'):
                    if link.to_node.bl_idname == 'ShaderNodeMixRGB':
                        next_mix = link.to_node
                        break
            if next_mix is None:
                break
            depth += 1
            cur = next_mix
        return depth

    def _sort_key(tex):
        uv_n = _uv_trailing_digit(tex)
        return (
            0 if uv_n is not None else 1,
            uv_n if uv_n is not None else 0,
            -_downstream_mix_depth(tex),
            tex.name,
        )

    return sorted(tex_nodes, key=_sort_key)


def _extract_texture_layers(nodes, links, logger, image_cache=None):
    tex_nodes = _order_texture_nodes(_find_nodes(nodes, 'ShaderNodeTexImage'), links)
    layers = []
    for layer_index, tex_node in enumerate(tex_nodes):
        layer = _describe_texture_node(
            tex_node, nodes, links, logger, image_cache, layer_index=layer_index
        )
        if layer is not None:
            layers.append(layer)
    return layers


def _describe_texture_node(tex_node, nodes, links, logger, image_cache=None,
                           layer_index=0):
    image = tex_node.image
    if image is None:
        return None

    ir_image = _extract_image(image, image_cache)

    coord_type = CoordType.UV
    uv_index = layer_index
    mapping_node = None

    _upstream = []
    _seen = set()
    for link in links:
        if link.to_node == tex_node and link.to_socket.name == 'Vector':
            _upstream.append((link.from_node, link.from_socket.name)); break
    while _upstream:
        src, from_socket = _upstream.pop()
        if src.name in _seen: continue
        _seen.add(src.name)
        if src.bl_idname == 'ShaderNodeMapping' and mapping_node is None:
            mapping_node = src
        elif src.bl_idname == 'ShaderNodeUVMap':
            import re
            m = re.search(r'(\d+)$', src.uv_map or '')
            if m:
                uv_index = int(m.group(1))
        elif src.bl_idname == 'ShaderNodeTexCoord':
            if from_socket == 'Reflection':
                coord_type = CoordType.REFLECTION
        for l2 in links:
            if l2.to_node == src:
                _upstream.append((l2.from_node, l2.from_socket.name))

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

    wrap_s, wrap_t = _detect_per_axis_wrap(tex_node, links)
    if wrap_s is None or wrap_t is None:
        wrap_map = {
            'REPEAT': WrapMode.REPEAT,
            'EXTEND': WrapMode.CLAMP,
            'CLIP': WrapMode.CLAMP,
            'MIRROR': WrapMode.MIRROR,
        }
        ext = tex_node.extension if hasattr(tex_node, 'extension') else 'REPEAT'
        fallback = wrap_map.get(ext, WrapMode.REPEAT)
        if wrap_s is None: wrap_s = fallback
        if wrap_t is None: wrap_t = fallback

    interp_map = {
        'Closest': TextureInterpolation.CLOSEST,
        'Cubic': TextureInterpolation.CUBIC,
    }
    interpolation = interp_map.get(tex_node.interpolation, None)

    color_blend, blend_factor, is_bump = _detect_blend_mode(tex_node, links)
    alpha_blend = _detect_alpha_blend_mode(tex_node, links)

    if coord_type == CoordType.REFLECTION and not is_bump:
        lightmap_channel = LightmapChannel.EXTENSION
    else:
        lightmap_channel = LightmapChannel.DIFFUSE

    return IRTextureLayer(
        image=ir_image,
        coord_type=coord_type,
        uv_index=uv_index,
        rotation=rotation,
        scale=scale,
        translation=translation,
        wrap_s=wrap_s,
        wrap_t=wrap_t,
        repeat_s=repeat_s,
        repeat_t=repeat_t,
        interpolation=interpolation,
        color_blend=color_blend,
        alpha_blend=alpha_blend,
        blend_factor=blend_factor,
        lightmap_channel=lightmap_channel,
        is_bump=is_bump,
    )


def _detect_alpha_blend_mode(tex_node, links):
    math_blend_map = {
        'MULTIPLY': LayerBlendMode.MULTIPLY,
        'ADD': LayerBlendMode.ADD,
        'SUBTRACT': LayerBlendMode.SUBTRACT,
    }
    mix_blend_map = {
        'MIX': LayerBlendMode.MIX,
        'MULTIPLY': LayerBlendMode.MULTIPLY,
        'ADD': LayerBlendMode.ADD,
        'SUBTRACT': LayerBlendMode.SUBTRACT,
    }
    for link in links:
        if link.from_node != tex_node or link.from_socket.name != 'Alpha':
            continue
        target = link.to_node
        idname = getattr(target, 'bl_idname', '')
        op = getattr(target, 'operation', None)
        if idname == 'ShaderNodeMath' and op in math_blend_map:
            return math_blend_map[op]
        if idname == 'ShaderNodeMixRGB':
            return mix_blend_map.get(target.blend_type, LayerBlendMode.MIX)
    return LayerBlendMode.NONE


def _detect_blend_mode(tex_node, links):
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
            return LayerBlendMode.REPLACE, 1.0, False

    return LayerBlendMode.REPLACE, 1.0, False


def _extract_image(bpy_image, cache=None):
    if cache is not None:
        cached = cache.get(id(bpy_image))
        if cached is not None:
            return cached

    width = bpy_image.size[0]
    height = bpy_image.size[1]

    pixel_count = width * height
    if pixel_count == 0:
        pixels = b''
    else:
        flat = list(bpy_image.pixels)
        pixel_bytes = bytearray(pixel_count * 4)
        for i in range(pixel_count * 4):
            pixel_bytes[i] = min(255, max(0, int(flat[i] * 255 + 0.5)))
        pixels = bytes(pixel_bytes)

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
