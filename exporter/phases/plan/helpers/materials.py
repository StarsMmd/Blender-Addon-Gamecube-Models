"""Plan BRMaterial list into IRMaterial list.

Pure — no bpy. Reads each BRMaterial's BRNodeGraph (a faithful snapshot
of the source Blender shader graph) and produces an IRMaterial. This
inverts the importer's `IRMaterial → BRNodeGraph → bpy material` plan,
recovering GX combiner / texture-layer / lighting semantics from the
node arrangement.

The decoder is structured around a small `_GraphView` helper that
indexes the BRNodeGraph by node name + by ``(to_node, to_input)``
socket address, so finding "the node feeding texture T's Vector input"
or "the BSDF Principled in this material" is O(1) without re-walking
the link list.
"""
import math
import re

try:
    from .....shared.IR.material import (
        IRMaterial, IRTextureLayer, IRImage,
    )
    from .....shared.IR.enums import (
        ColorSource, LightingModel, CoordType, WrapMode,
        TextureInterpolation, LayerBlendMode, LightmapChannel,
        GXTextureFormat,
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
        GXTextureFormat,
    )
    from shared.helpers.srgb import linear_to_srgb, srgb_to_linear
    from shared.helpers.logger import StubLogger


_SHINY_NAMES = frozenset((
    'shiny_route_shader', 'shiny_route_mix',
    'shiny_bright_shader', 'shiny_bright_mix',
    'dat_ambient_emission', 'dat_ambient_add',
))


def plan_material(br_material, logger=StubLogger(), image_cache=None):
    """Convert one BRMaterial to an IRMaterial.

    In: br_material (BRMaterial); logger; image_cache (optional dict
        id(BRImage) → IRImage, shared across materials so identical
        images dedup at the IR level).
    Out: IRMaterial, or None if the material has no node graph.
    """
    if br_material is None or not br_material.node_graph.nodes:
        return None

    if image_cache is None:
        image_cache = {}

    view = _GraphView(br_material.node_graph)

    principled = view.find_node('ShaderNodeBsdfPrincipled')
    emission = view.find_node('ShaderNodeEmission')

    lighting = _classify_lighting(principled, emission)

    diffuse_color = _extract_rgb_node_color(view, 'diffuse') or (0.7, 0.7, 0.7, 1.0)
    if principled is not None and diffuse_color == (0.7, 0.7, 0.7, 1.0):
        base_color = principled.input_defaults.get('Base Color', (0.0, 0.0, 0.0, 1.0))
        diffuse_color = _linear_to_srgb_rgba(base_color)

    ambient_color = _extract_ambient(view)

    specular_color = _extract_specular_color(principled, diffuse_color)

    alpha = 1.0
    if principled is not None and 'Alpha' in principled.input_defaults:
        alpha = float(principled.input_defaults['Alpha'])

    shininess, enable_specular = _extract_specular_settings(principled)

    color_source, alpha_source = _detect_color_sources(view)
    texture_layers = _extract_texture_layers(view, logger, image_cache)

    is_translucent = _detect_translucent(view, principled)

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

    logger.debug(
        "    material '%s': diffuse=%s alpha=%.2f shininess=%.1f lighting=%s textures=%d",
        br_material.name, diffuse_color, alpha, shininess,
        lighting.value, len(texture_layers))

    return ir_material


def plan_materials(br_materials, logger=StubLogger()):
    """Convert a list of BRMaterials to IRMaterials, deduping IRImages
    across the list so identical source images share an IRImage."""
    image_cache = {}
    return [plan_material(m, logger=logger, image_cache=image_cache)
            for m in br_materials]


# ---------------------------------------------------------------------------
# GraphView — O(1) lookups over a BRNodeGraph
# ---------------------------------------------------------------------------

class _GraphView:
    """Indexed view over a BRNodeGraph. Provides node-by-name and
    incoming-socket lookups so the decoder doesn't re-scan the link
    list on every traversal step."""

    def __init__(self, graph):
        self.graph = graph
        self.nodes_by_name = {n.name: n for n in graph.nodes}
        # Incoming: (to_node_name, to_input_socket) → BRLink
        self._incoming = {}
        # Outgoing: from_node_name → [BRLink, ...]
        self._outgoing = {}
        for link in graph.links:
            self._incoming[(link.to_node, link.to_input)] = link
            self._outgoing.setdefault(link.from_node, []).append(link)

    def find_node(self, node_type):
        """First node of the given type, skipping shiny / ambient marker
        nodes that the importer adds but don't belong to the material's
        own surface chain."""
        for n in self.graph.nodes:
            if n.node_type == node_type and n.name not in _SHINY_NAMES:
                return n
        return None

    def find_nodes(self, node_type):
        return [n for n in self.graph.nodes
                if n.node_type == node_type and n.name not in _SHINY_NAMES]

    def has_node_type(self, node_type):
        """True if ANY node (including marker nodes) matches."""
        return any(n.node_type == node_type for n in self.graph.nodes)

    def link_into(self, to_node_name, to_input):
        """The single BRLink feeding (to_node_name, to_input), or None."""
        return self._incoming.get((to_node_name, to_input))

    def is_linked(self, to_node_name, to_input):
        return (to_node_name, to_input) in self._incoming

    def upstream(self, to_node_name, to_input):
        """Convenience: return (source_node, source_socket_name) for the
        link feeding this socket, or (None, None)."""
        link = self._incoming.get((to_node_name, to_input))
        if link is None:
            return None, None
        return self.nodes_by_name.get(link.from_node), link.from_output

    def outgoing_from(self, from_node_name):
        """List of BRLinks leaving this node."""
        return self._outgoing.get(from_node_name, [])


# ---------------------------------------------------------------------------
# Lighting + colours
# ---------------------------------------------------------------------------

def _classify_lighting(principled, emission):
    """LIT vs UNLIT classification — semantic, not pattern.

    A material is functionally UNLIT when its lit-surface path
    (Principled BSDF) contributes nothing: Base Color is unlinked AND
    black, so the BSDF integrand is zero regardless of specular. Any
    visible output then comes from an Emission node.
    """
    if principled is None and emission is not None:
        return LightingModel.UNLIT
    if principled is not None and emission is not None and _bsdf_is_dead(principled):
        return LightingModel.UNLIT
    return LightingModel.LIT


def _bsdf_is_dead(principled):
    base = principled.input_defaults.get('Base Color')
    if base is None:
        return False
    if base[0] > 0.01 or base[1] > 0.01 or base[2] > 0.01:
        return False
    return True


def _extract_ambient(view):
    """Pull the ambient colour from the importer-built
    ``dat_ambient_emission`` marker node, if present."""
    for n in view.graph.nodes:
        if n.name == 'dat_ambient_emission':
            color = n.input_defaults.get('Color', (0.5, 0.5, 0.5, 1.0))
            return _linear_to_srgb_rgba(color)
    return (0.5, 0.5, 0.5, 1.0)


def _extract_specular_color(principled, diffuse_color):
    """Reverse Blender's Specular-Tint encoding.

    Forward: ``specular = mix(white, base, tint) = 1 + tint*(base-1)``
    Reverse: ``specular_color = 1 + tint * (diffuse - 1)``
    """
    if principled is None:
        return (1.0, 1.0, 1.0, 1.0)
    tint = principled.input_defaults.get('Specular Tint')
    if tint is None or not hasattr(tint, '__len__') or len(tint) < 3:
        return (1.0, 1.0, 1.0, 1.0)
    spec = [0.0, 0.0, 0.0, 1.0]
    for c in range(3):
        diff_linear = srgb_to_linear(diffuse_color[c])
        spec_linear = 1.0 + tint[c] * (diff_linear - 1.0)
        spec[c] = linear_to_srgb(max(0.0, min(1.0, spec_linear)))
    return tuple(spec)


def _extract_specular_settings(principled):
    """Recover (shininess, enable_specular) from the Principled BSDF's
    Specular IOR Level. The importer writes ``shininess/50`` when
    specular is enabled and ``0`` when disabled — values above the
    epsilon are treated as enabled."""
    shininess = 50.0
    enable_specular = False
    if principled is None:
        return shininess, enable_specular
    spec_val = principled.input_defaults.get('Specular IOR Level')
    if spec_val is None:
        return shininess, enable_specular
    if spec_val > 0.001:
        shininess = float(spec_val) * 50.0
        enable_specular = True
    return shininess, enable_specular


def _extract_rgb_node_color(view, hint):
    """Find a ShaderNodeRGB and return its sRGB colour. Disambiguates
    multiple RGB nodes by chasing their first downstream link's
    socket name (e.g. an RGB feeding a Combine called "diffuse")."""
    rgb_nodes = view.find_nodes('ShaderNodeRGB')
    if not rgb_nodes:
        return None

    if len(rgb_nodes) == 1 and hint == 'diffuse':
        return _linear_to_srgb_rgba(rgb_nodes[0].properties.get('color', (0.0, 0.0, 0.0, 1.0)))

    for rgb in rgb_nodes:
        for link in view.outgoing_from(rgb.name):
            socket_name = (link.to_input or '').lower()
            if hint in socket_name:
                return _linear_to_srgb_rgba(rgb.properties.get('color', (0.0, 0.0, 0.0, 1.0)))

    idx = {'diffuse': 0, 'ambient': 1, 'specular': 2}.get(hint, 0)
    if idx < len(rgb_nodes):
        return _linear_to_srgb_rgba(rgb_nodes[idx].properties.get('color', (0.0, 0.0, 0.0, 1.0)))
    return None


def _linear_to_srgb_rgba(color):
    return (
        linear_to_srgb(color[0]),
        linear_to_srgb(color[1]),
        linear_to_srgb(color[2]),
        color[3] if len(color) >= 4 else 1.0,
    )


def _detect_color_sources(view):
    """Detect whether colours come from material, vertex layers, or
    both. Driven by the presence of ``ShaderNodeAttribute`` nodes
    pointing at the importer's ``color_0`` / ``alpha_0`` attributes."""
    has_vertex_color = False
    has_vertex_alpha = False
    for n in view.find_nodes('ShaderNodeAttribute'):
        attr = n.properties.get('attribute_name', '')
        if attr == 'color_0':
            has_vertex_color = True
        elif attr == 'alpha_0':
            has_vertex_alpha = True

    rgb_nodes = view.find_nodes('ShaderNodeRGB')
    if has_vertex_color:
        color_source = ColorSource.BOTH if rgb_nodes else ColorSource.VERTEX
    else:
        color_source = ColorSource.MATERIAL

    if has_vertex_alpha:
        alpha_source = ColorSource.BOTH if has_vertex_color else ColorSource.VERTEX
    else:
        alpha_source = ColorSource.MATERIAL
    return color_source, alpha_source


# ---------------------------------------------------------------------------
# Translucency
# ---------------------------------------------------------------------------

def _detect_translucent(view, principled):
    """A material is translucent when:
      1. The graph contains a Transparent BSDF (importer's UNLIT
         translucent path), OR
      2. The Principled BSDF's Alpha socket is wired AND the texture
         feeding that wire actually contains sub-1.0 alpha pixels.

    (2)'s pixel check matters because GLB/FBX rips wire Alpha on every
    material regardless of intent — uniformly-1.0 alpha would otherwise
    misclassify as translucent.
    """
    if view.has_node_type('ShaderNodeBsdfTransparent'):
        return True
    if principled is None or not view.is_linked(principled.name, 'Alpha'):
        return False
    return _alpha_wire_has_transparency(view, principled.name, 'Alpha', threshold=0.5)


def _alpha_wire_has_transparency(view, to_node, to_input, threshold=0.5,
                                  sample_count=1024):
    """DFS upstream from ``(to_node, to_input)``, find any
    ShaderNodeTexImage feeding it, and check its image alpha
    histogram."""
    visited = set()
    stack = []
    link = view.link_into(to_node, to_input)
    if link is not None:
        stack.append(link.from_node)

    while stack:
        node_name = stack.pop()
        if node_name in visited or node_name not in view.nodes_by_name:
            continue
        visited.add(node_name)
        node = view.nodes_by_name[node_name]

        if node.node_type == 'ShaderNodeTexImage' and node.image_ref is not None:
            img = node.image_ref
            pixels = img.pixels
            if pixels and img.width > 0 and img.height > 0:
                n_px = img.width * img.height
                step = max(1, n_px // sample_count)
                # Pixels are RGBA u8 bytes.
                threshold_u8 = int(threshold * 255)
                for i in range(0, n_px, step):
                    if pixels[i * 4 + 3] < threshold_u8:
                        return True

        for upstream_link in view.graph.links:
            if upstream_link.to_node == node_name:
                stack.append(upstream_link.from_node)
    return False


# ---------------------------------------------------------------------------
# Texture layers
# ---------------------------------------------------------------------------

def _extract_texture_layers(view, logger, image_cache):
    tex_nodes = _order_texture_nodes(view)
    layers = []
    for layer_index, tex_node in enumerate(tex_nodes):
        layer = _describe_texture_node(view, tex_node, layer_index, image_cache)
        if layer is not None:
            layers.append(layer)
    return layers


def _order_texture_nodes(view):
    """Sort ShaderNodeTexImage nodes into layer order. Two signals,
    in priority:

    1. UV-map trailing digit (``uvtex_3`` → layer 3) found by walking
       the texture's Vector chain to a ShaderNodeUVMap.
    2. Downstream MixRGB chain depth (fallback) — layer 0 has the most
       MixRGBs descending from it.
    """
    tex_nodes = view.find_nodes('ShaderNodeTexImage')

    def _uv_trailing_digit(tex):
        link = view.link_into(tex.name, 'Vector')
        if link is None:
            return None
        visited = set()
        stack = [link.from_node]
        while stack:
            cur = stack.pop()
            if cur in visited or cur not in view.nodes_by_name:
                continue
            visited.add(cur)
            node = view.nodes_by_name[cur]
            if node.node_type == 'ShaderNodeUVMap':
                m = re.search(r'(\d+)$', node.properties.get('uv_map', '') or '')
                return int(m.group(1)) if m else None
            for upstream in view.graph.links:
                if upstream.to_node == cur:
                    stack.append(upstream.from_node)
        return None

    def _downstream_mix_depth(tex):
        depth = 0
        cur = tex.name
        visited = set()
        while True:
            if cur in visited:
                break
            visited.add(cur)
            next_mix = None
            for link in view.outgoing_from(cur):
                if link.from_output in ('Color', 'Result'):
                    target = view.nodes_by_name.get(link.to_node)
                    if target is not None and target.node_type == 'ShaderNodeMixRGB':
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


def _describe_texture_node(view, tex_node, layer_index, image_cache):
    if tex_node.image_ref is None:
        return None

    ir_image = _br_image_to_ir(tex_node.image_ref, image_cache)

    coord_type = CoordType.UV
    uv_index = layer_index
    mapping_node = None

    upstream = []
    seen = set()
    link = view.link_into(tex_node.name, 'Vector')
    if link is not None:
        upstream.append((link.from_node, link.from_output))
    while upstream:
        node_name, from_socket = upstream.pop()
        if node_name in seen or node_name not in view.nodes_by_name:
            continue
        seen.add(node_name)
        node = view.nodes_by_name[node_name]

        if node.node_type == 'ShaderNodeMapping' and mapping_node is None:
            mapping_node = node
        elif node.node_type == 'ShaderNodeUVMap':
            m = re.search(r'(\d+)$', node.properties.get('uv_map', '') or '')
            if m:
                uv_index = int(m.group(1))
        elif node.node_type == 'ShaderNodeTexCoord':
            if from_socket == 'Reflection':
                coord_type = CoordType.REFLECTION

        for upstream_link in view.graph.links:
            if upstream_link.to_node == node_name:
                upstream.append((upstream_link.from_node, upstream_link.from_output))

    rotation = (0.0, 0.0, 0.0)
    scale = (1.0, 1.0, 1.0)
    translation = (0.0, 0.0, 0.0)
    if mapping_node is not None:
        rotation = tuple(mapping_node.input_defaults.get('Rotation', (0.0, 0.0, 0.0)))[:3]
        scale = tuple(mapping_node.input_defaults.get('Scale', (1.0, 1.0, 1.0)))[:3]
        translation = tuple(mapping_node.input_defaults.get('Location', (0.0, 0.0, 0.0)))[:3]

    repeat_s = 1
    repeat_t = 1
    vec_link = view.link_into(tex_node.name, 'Vector')
    if vec_link is not None:
        upstream_node = view.nodes_by_name.get(vec_link.from_node)
        if (upstream_node is not None
                and upstream_node.node_type == 'ShaderNodeVectorMath'
                and upstream_node.properties.get('operation') == 'MULTIPLY'):
            scale_input = upstream_node.input_defaults.get('Vector_001')
            if scale_input is None:
                # Blender exposes the second Vector socket either as the
                # name 'Vector' (duplicate) or as 'Vector_001' depending
                # on version. Walk the input_defaults for the second hit.
                second = None
                count = 0
                for k, v in upstream_node.input_defaults.items():
                    if k.startswith('Vector'):
                        count += 1
                        if count == 2:
                            second = v
                            break
                scale_input = second
            if scale_input is not None and hasattr(scale_input, '__len__') and len(scale_input) >= 2:
                repeat_s = max(1, int(round(scale_input[0])))
                repeat_t = max(1, int(round(scale_input[1])))

    wrap_s, wrap_t = _detect_per_axis_wrap(view, tex_node)
    if wrap_s is None or wrap_t is None:
        wrap_map = {
            'REPEAT': WrapMode.REPEAT,
            'EXTEND': WrapMode.CLAMP,
            'CLIP': WrapMode.CLAMP,
            'MIRROR': WrapMode.MIRROR,
        }
        ext = tex_node.properties.get('extension', 'REPEAT')
        fallback = wrap_map.get(ext, WrapMode.REPEAT)
        if wrap_s is None: wrap_s = fallback
        if wrap_t is None: wrap_t = fallback

    interp_map = {
        'Closest': TextureInterpolation.CLOSEST,
        'Cubic': TextureInterpolation.CUBIC,
    }
    interpolation = interp_map.get(tex_node.properties.get('interpolation'), None)

    color_blend, blend_factor, is_bump = _detect_blend_mode(view, tex_node)
    alpha_blend = _detect_alpha_blend_mode(view, tex_node)

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


def _detect_per_axis_wrap(view, tex_node):
    """The importer builds ``Separate → per-axis Math → Combine`` for any
    asymmetric wrap (and always for MIRROR). Detect the chain and read
    each axis's op back into a WrapMode."""
    vec_link = view.link_into(tex_node.name, 'Vector')
    if vec_link is None:
        return None, None
    combine = view.nodes_by_name.get(vec_link.from_node)
    if combine is None or combine.node_type != 'ShaderNodeCombineXYZ':
        return None, None

    def _trace_axis(axis_socket_name):
        op_link = view.link_into(combine.name, axis_socket_name)
        if op_link is None:
            return None
        op_node = view.nodes_by_name.get(op_link.from_node)
        if op_node is None:
            return None
        if op_node.node_type == 'ShaderNodeMath':
            op = op_node.properties.get('operation')
            if op == 'MINIMUM':
                # CLAMP encodes as MAXIMUM(0.0) → MINIMUM(1.0).
                upstream_link = view.link_into(op_node.name, 'Value')
                if upstream_link is not None:
                    upstream_node = view.nodes_by_name.get(upstream_link.from_node)
                    if (upstream_node is not None
                            and upstream_node.node_type == 'ShaderNodeMath'
                            and upstream_node.properties.get('operation') == 'MAXIMUM'):
                        return WrapMode.CLAMP
                return None
            if op == 'FRACT':
                return WrapMode.REPEAT
            if op == 'PINGPONG':
                return WrapMode.MIRROR
        return None

    return _trace_axis('X'), _trace_axis('Y')


def _detect_blend_mode(view, tex_node):
    """Detect the colour blend mode + bump flag by inspecting what the
    texture's Color output feeds. Returns (LayerBlendMode, factor, is_bump).

    The importer wires ALPHA_MASK / RGB_MASK by routing the texture's
    own Alpha/Color into a downstream MixRGB's Fac socket — that's the
    disambiguator from a plain MIX (constant Fac) blend.
    """
    blend_type_map = {
        'MIX': LayerBlendMode.MIX,
        'MULTIPLY': LayerBlendMode.MULTIPLY,
        'ADD': LayerBlendMode.ADD,
        'SUBTRACT': LayerBlendMode.SUBTRACT,
    }

    for link in view.outgoing_from(tex_node.name):
        if link.from_output != 'Color':
            continue
        target = view.nodes_by_name.get(link.to_node)
        if target is None:
            continue

        if target.node_type == 'ShaderNodeMixRGB':
            fac_link = view.link_into(target.name, 'Fac')
            if fac_link is not None and fac_link.from_node == tex_node.name:
                if fac_link.from_output == 'Alpha':
                    return LayerBlendMode.ALPHA_MASK, 1.0, False
                if fac_link.from_output == 'Color':
                    return LayerBlendMode.RGB_MASK, 1.0, False
            blend_type = blend_type_map.get(
                target.properties.get('blend_type'), LayerBlendMode.REPLACE)
            factor = target.input_defaults.get('Fac', 1.0)
            return blend_type, float(factor), False

        if target.node_type == 'ShaderNodeBump':
            return LayerBlendMode.MIX, 0.0, True

        return LayerBlendMode.REPLACE, 1.0, False

    return LayerBlendMode.REPLACE, 1.0, False


def _detect_alpha_blend_mode(view, tex_node):
    """Mirror of `_detect_blend_mode` for the Alpha output, which the
    importer threads through its own MixRGB / Math chain to encode
    alpha-side blending semantics for multi-texture materials."""
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
    for link in view.outgoing_from(tex_node.name):
        if link.from_output != 'Alpha':
            continue
        target = view.nodes_by_name.get(link.to_node)
        if target is None:
            continue
        if target.node_type == 'ShaderNodeMath':
            op = target.properties.get('operation')
            if op in math_blend_map:
                return math_blend_map[op]
        elif target.node_type == 'ShaderNodeMixRGB':
            return mix_blend_map.get(
                target.properties.get('blend_type'), LayerBlendMode.MIX)
    return LayerBlendMode.NONE


# ---------------------------------------------------------------------------
# Image conversion
# ---------------------------------------------------------------------------

def _br_image_to_ir(br_image, cache):
    """Convert a BRImage to an IRImage, sharing one IRImage per source
    BRImage so downstream compose dedup collapses identical textures."""
    key = id(br_image)
    cached = cache.get(key)
    if cached is not None:
        return cached

    try:
        gx_format = GXTextureFormat(br_image.gx_format_override or 'AUTO')
    except (ValueError, KeyError):
        gx_format = GXTextureFormat.AUTO

    ir_image = IRImage(
        name=br_image.name,
        width=br_image.width,
        height=br_image.height,
        pixels=br_image.pixels,
        image_id=0,
        palette_id=0,
        gx_format_override=gx_format,
    )
    cache[key] = ir_image
    return ir_image
