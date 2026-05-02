"""Snapshot Blender materials into BRMaterial dataclasses.

The shader node tree is serialised faithfully into a BRNodeGraph: every
node becomes a BRNode (node_type = bl_idname, input defaults captured by
socket name, type-specific attributes captured into ``properties``,
texture nodes carry a BRImage on ``image_ref``); every wire becomes a
BRLink with from/to node names and socket names. Plan
(`plan_material`) reads the graph and produces an IRMaterial — the
"is this material LIT, what does each texture layer mean, what blend
mode applies" interpretation lives entirely on the plan side.
"""
import bpy

try:
    from .....shared.BR.materials import (
        BRMaterial, BRNodeGraph, BRNode, BRLink, BRImage,
    )
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.BR.materials import (
        BRMaterial, BRNodeGraph, BRNode, BRLink, BRImage,
    )
    from shared.helpers.logger import StubLogger


# Node attributes the plan-side decoder reads — captured into BRNode.properties
# so the decoder doesn't need a bpy node reference. Each entry is the bpy
# attribute name; the BR property uses the same key.
_NODE_PROPERTY_KEYS = {
    'ShaderNodeMath': ('operation',),
    'ShaderNodeMixRGB': ('blend_type',),
    'ShaderNodeVectorMath': ('operation',),
    'ShaderNodeTexImage': ('extension', 'interpolation'),
    'ShaderNodeAttribute': ('attribute_name',),
    'ShaderNodeUVMap': ('uv_map',),
}


def describe_material(blender_mat, logger=StubLogger(),
                      cache=None, image_cache=None):
    """Read one Blender material into a BRMaterial.

    In: blender_mat (bpy.types.Material with use_nodes=True); logger;
        cache (dict id(blender_mat) → BRMaterial; reuses the same
        instance for repeated calls so downstream dedup collapses
        DObjects sharing the material); image_cache (dict id(bpy_image)
        → BRImage; shared across materials so one image produces one
        BRImage instance).
    Out: BRMaterial, or None if the material lacks a node tree.
    """
    if not blender_mat or not blender_mat.use_nodes:
        return None

    cache_key = id(blender_mat)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    if image_cache is None:
        image_cache = {}

    node_graph = _serialise_node_graph(blender_mat.node_tree, image_cache)
    br = BRMaterial(
        name=blender_mat.name,
        node_graph=node_graph,
        use_backface_culling=blender_mat.use_backface_culling,
        blend_method=getattr(blender_mat, 'blend_method', None),
        dedup_key=(id(blender_mat),),
    )

    if cache is not None:
        cache[cache_key] = br
    return br


def _serialise_node_graph(node_tree, image_cache):
    nodes = [_serialise_node(n, image_cache) for n in node_tree.nodes]
    links = [
        BRLink(
            from_node=link.from_node.name,
            from_output=link.from_socket.name,
            to_node=link.to_node.name,
            to_input=link.to_socket.name,
        )
        for link in node_tree.links
    ]
    return BRNodeGraph(nodes=nodes, links=links)


def _serialise_node(node, image_cache):
    bl_idname = node.bl_idname

    properties = {}
    for attr in _NODE_PROPERTY_KEYS.get(bl_idname, ()):
        if hasattr(node, attr):
            properties[attr] = getattr(node, attr)

    # ShaderNodeRGB exposes its colour on outputs[0]. Capture it on
    # ``properties['color']`` so the plan-side decoder doesn't need to
    # touch bpy output sockets.
    if bl_idname == 'ShaderNodeRGB':
        properties['color'] = tuple(node.outputs[0].default_value)

    # ShaderNodeMapping inputs are vector triples — captured by name as
    # 3-tuples so the plan can rebuild rotation / scale / translation.
    input_defaults = {}
    for inp in node.inputs:
        if inp.is_linked:
            continue
        try:
            value = inp.default_value
        except (AttributeError, RuntimeError):
            continue
        input_defaults[inp.name] = _coerce_default(value)

    image_ref = None
    if bl_idname == 'ShaderNodeTexImage' and node.image is not None:
        image_ref = _serialise_image(node.image, image_cache)

    return BRNode(
        node_type=bl_idname,
        name=node.name,
        properties=properties,
        input_defaults=input_defaults,
        image_ref=image_ref,
        location=tuple(node.location),
    )


def _coerce_default(value):
    """Turn a bpy default_value into a hashable / JSON-friendly Python
    value: floats stay floats, vectors/colours become tuples."""
    if hasattr(value, '__len__') and not isinstance(value, str):
        return tuple(float(c) for c in value)
    if isinstance(value, (int, float, bool, str)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _serialise_image(bpy_image, cache):
    key = id(bpy_image)
    cached = cache.get(key)
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

    br_image = BRImage(
        name=bpy_image.name,
        width=width,
        height=height,
        pixels=pixels,
        cache_key=(key,),
        gx_format_override=getattr(bpy_image, 'dat_gx_format', 'AUTO') or 'AUTO',
    )
    cache[key] = br_image
    return br_image
