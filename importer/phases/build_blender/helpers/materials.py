"""Execute a BR material spec as a Blender material.

Pure bpy walker — no shader decisions, no IR access. Walks BRNodeGraph
nodes + links and emits the corresponding ``nodes.new()`` / ``links.new()``
calls. All TEV, pixel-engine, and output-shader logic lives in the Plan
phase (``importer/phases/plan/helpers/materials.py``).
"""
import bpy
import numpy as np


def build_material(br_material, image_cache=None):
    """Create a Blender material from a BRMaterial spec.

    Args:
        br_material: BRMaterial with a fully populated BRNodeGraph.
        image_cache: dict caching bpy.data.images by ``BRImage.cache_key``.
            Shared across a model so multiple materials referencing the
            same image reuse the same bpy image.

    Returns:
        bpy.types.Material.
    """
    if image_cache is None:
        image_cache = {}

    mat = bpy.data.materials.new(br_material.name)
    mat.use_nodes = True
    if br_material.use_backface_culling:
        mat.use_backface_culling = True
    if br_material.blend_method is not None:
        mat.blend_method = br_material.blend_method

    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Clear the auto-created default nodes
    for existing in list(nodes):
        nodes.remove(existing)

    bpy_nodes = {}
    for br_node in br_material.node_graph.nodes:
        bpy_node = nodes.new(type=br_node.node_type)
        bpy_node.name = br_node.name
        if br_node.location is not None:
            bpy_node.location = br_node.location

        output_default = None
        for prop, value in br_node.properties.items():
            if prop == '_output_default':
                # RGB/Value nodes store their constant on outputs[0].default_value
                output_default = value
            else:
                setattr(bpy_node, prop, value)
        if output_default is not None:
            _set_output_default(bpy_node, output_default)

        for socket_key, value in br_node.input_defaults.items():
            _set_input_default(bpy_node, socket_key, value)

        if br_node.image_ref is not None:
            bpy_node.image = _resolve_image(br_node.image_ref, image_cache)

        bpy_nodes[br_node.name] = bpy_node

    for link in br_material.node_graph.links:
        from_node = bpy_nodes[link.from_node]
        to_node = bpy_nodes[link.to_node]
        from_socket = _resolve_socket(from_node.outputs, link.from_output)
        to_socket = _resolve_socket(to_node.inputs, link.to_input)
        links.new(from_socket, to_socket)

    return mat


def _set_output_default(node, value):
    """ShaderNodeRGB / ShaderNodeValue store their value on outputs[0]."""
    socket = node.outputs[0]
    if isinstance(value, (list, tuple)):
        socket.default_value[:] = list(value)
    else:
        socket.default_value = value


def _set_input_default(node, socket_key, value):
    socket = _resolve_socket(node.inputs, socket_key)
    if isinstance(value, (list, tuple)):
        socket.default_value[:] = list(value)
    else:
        socket.default_value = value


def _resolve_socket(collection, key):
    """Socket access: int → positional, str → by name."""
    if isinstance(key, int):
        return collection[key]
    return collection[key]


def _resolve_image(br_image, image_cache):
    """Get or create a bpy.data.images entry from a BRImage spec.

    Dedup by BRImage.cache_key — multiple materials referencing the same
    source image share the same bpy image.
    """
    if br_image is None:
        return None
    if br_image.cache_key in image_cache:
        return image_cache[br_image.cache_key]

    bpy_image = bpy.data.images.new(
        br_image.name, br_image.width, br_image.height, alpha=True,
    )
    bpy_image.pixels = np.frombuffer(br_image.pixels, dtype=np.uint8).astype(np.float32) / 255.0
    bpy_image.alpha_mode = br_image.alpha_mode
    if br_image.pack:
        bpy_image.pack()
    if br_image.gx_format_override is not None and hasattr(bpy_image, 'dat_gx_format'):
        bpy_image.dat_gx_format = br_image.gx_format_override

    image_cache[br_image.cache_key] = bpy_image
    return bpy_image
