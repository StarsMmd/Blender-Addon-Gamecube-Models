"""Build and insert shiny color filter shader nodes.

Creates two node groups for the PKX shiny color transformation:
  - ShinyRoute: channel routing (swizzle) — applied BEFORE vertex color multiply
  - ShinyBright: brightness scaling — applied AFTER vertex color multiply

This separation ensures that channel routing only affects texture/material
colors, not vertex colors. Both stages are driven by a single dat_pkx_shiny
toggle on the armature.

The node groups are rebuilt whenever any shiny parameter property changes,
so all 8 parameters (4 routing + 4 brightness) can be tweaked live.
"""
import bpy

try:
    from ....shared.IR.enums import ShinyChannel
except (ImportError, SystemError):
    from shared.IR.enums import ShinyChannel

# Mapping from property enum identifiers to ShinyChannel
_PROP_TO_CHANNEL = {
    'RED': ShinyChannel.RED,
    'GREEN': ShinyChannel.GREEN,
    'BLUE': ShinyChannel.BLUE,
    'ALPHA': ShinyChannel.ALPHA,
}

# Mapping from ShinyChannel to property enum identifier
_CHANNEL_TO_PROP = {v: k for k, v in _PROP_TO_CHANNEL.items()}


# ---------------------------------------------------------------------------
# Node group construction
# ---------------------------------------------------------------------------

def build_shiny_route_node_group(shiny_filter, name):
    """Create a node group that performs channel routing (swizzle).

    Args:
        shiny_filter: IRShinyFilter with channel_routing.
        name: Name for the node group (e.g. "ShinyRoute_model_name").

    Returns:
        bpy.types.ShaderNodeTree (the node group).
    """
    group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    group.interface.new_socket('Color', in_out='INPUT', socket_type='NodeSocketColor')
    group.interface.new_socket('Color', in_out='OUTPUT', socket_type='NodeSocketColor')

    populate_shiny_route_node_group(group, shiny_filter.channel_routing)
    return group


def build_shiny_bright_node_group(shiny_filter, name):
    """Create a node group that performs per-channel brightness scaling.

    Args:
        shiny_filter: IRShinyFilter with brightness.
        name: Name for the node group (e.g. "ShinyBright_model_name").

    Returns:
        bpy.types.ShaderNodeTree (the node group).
    """
    group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    group.interface.new_socket('Color', in_out='INPUT', socket_type='NodeSocketColor')
    group.interface.new_socket('Color', in_out='OUTPUT', socket_type='NodeSocketColor')

    populate_shiny_bright_node_group(group, shiny_filter.brightness)
    return group


def populate_shiny_route_node_group(group, routing):
    """Populate a node group with channel routing (swizzle) nodes.

    Clears existing nodes and rebuilds. Since all material group node
    instances reference this group, changes propagate automatically.

    Args:
        group: bpy.types.ShaderNodeTree (the node group to populate).
        routing: tuple of 4 ShinyChannel values (R, G, B, A output mapping).
    """
    nodes = group.nodes
    links = group.links
    nodes.clear()

    group_in = nodes.new('NodeGroupInput')
    group_out = nodes.new('NodeGroupOutput')

    # Separate Color → R, G, B
    separate = nodes.new('ShaderNodeSeparateColor')
    separate.mode = 'RGB'
    links.new(group_in.outputs[0], separate.inputs[0])

    needs_alpha_input = any(
        routing[i] == ShinyChannel.ALPHA for i in range(4)
    )

    channel_sources = {
        ShinyChannel.RED: separate.outputs[0],
        ShinyChannel.GREEN: separate.outputs[1],
        ShinyChannel.BLUE: separate.outputs[2],
    }

    if needs_alpha_input:
        has_alpha_socket = any(
            item.name == 'Alpha' and item.in_out == 'INPUT'
            for item in group.interface.items_tree
        )
        if not has_alpha_socket:
            group.interface.new_socket('Alpha', in_out='INPUT', socket_type='NodeSocketFloat')
        alpha_input = group_in.outputs[1]
        channel_sources[ShinyChannel.ALPHA] = alpha_input
    else:
        for item in list(group.interface.items_tree):
            if item.name == 'Alpha' and item.in_out == 'INPUT':
                group.interface.remove(item)
                break
        channel_sources[ShinyChannel.ALPHA] = None

    # Route each output channel from its source
    routed = []
    for i in range(3):  # R, G, B only
        source = channel_sources[routing[i]]
        if source is not None:
            routed.append(source)
        else:
            value = nodes.new('ShaderNodeValue')
            value.outputs[0].default_value = 0.0
            routed.append(value.outputs[0])

    # Recombine RGB
    combine = nodes.new('ShaderNodeCombineColor')
    combine.mode = 'RGB'
    links.new(routed[0], combine.inputs[0])
    links.new(routed[1], combine.inputs[1])
    links.new(routed[2], combine.inputs[2])

    # Gamma: linearize (sRGB → linear) for Blender's scene-linear pipeline
    gamma = nodes.new('ShaderNodeGamma')
    gamma.inputs[1].default_value = 2.2
    links.new(combine.outputs[0], gamma.inputs[0])

    links.new(gamma.outputs[0], group_out.inputs[0])

    _auto_layout_node_group(nodes, links)


def populate_shiny_bright_node_group(group, brightness):
    """Populate a node group with per-channel brightness scaling.

    Args:
        group: bpy.types.ShaderNodeTree (the node group to populate).
        brightness: tuple of 4 floats in [-1.0, 1.0].
    """
    nodes = group.nodes
    links = group.links
    nodes.clear()

    group_in = nodes.new('NodeGroupInput')
    group_out = nodes.new('NodeGroupOutput')

    # Separate Color → R, G, B
    separate = nodes.new('ShaderNodeSeparateColor')
    separate.mode = 'RGB'
    links.new(group_in.outputs[0], separate.inputs[0])

    channel_names = ['R', 'G', 'B']
    scaled = []
    for i in range(3):
        mult = nodes.new('ShaderNodeMath')
        mult.operation = 'MULTIPLY'
        mult.name = 'Brightness_%s' % channel_names[i]
        links.new(separate.outputs[i], mult.inputs[0])
        mult.inputs[1].default_value = brightness[i] + 1.0  # [-1,1] → [0,2]
        scaled.append(mult.outputs[0])

    # Recombine RGB
    combine = nodes.new('ShaderNodeCombineColor')
    combine.mode = 'RGB'
    links.new(scaled[0], combine.inputs[0])
    links.new(scaled[1], combine.inputs[1])
    links.new(scaled[2], combine.inputs[2])

    links.new(combine.outputs[0], group_out.inputs[0])

    _auto_layout_node_group(nodes, links)


# ---------------------------------------------------------------------------
# Property setup and rebuild
# ---------------------------------------------------------------------------

def setup_shiny_properties(armature, shiny_filter, route_group_name, bright_group_name):
    """Initialize all shiny properties on the armature from an IRShinyFilter.

    Args:
        armature: The Blender armature object.
        shiny_filter: IRShinyFilter with channel_routing and brightness.
        route_group_name: Name of the ShinyRoute node group.
        bright_group_name: Name of the ShinyBright node group.
    """
    armature["dat_pkx_has_shiny"] = True
    armature["dat_pkx_shiny_route_group"] = route_group_name
    armature["dat_pkx_shiny_bright_group"] = bright_group_name

    armature.dat_pkx_shiny = False
    armature.dat_pkx_shiny_route_r = _CHANNEL_TO_PROP[shiny_filter.channel_routing[0]]
    armature.dat_pkx_shiny_route_g = _CHANNEL_TO_PROP[shiny_filter.channel_routing[1]]
    armature.dat_pkx_shiny_route_b = _CHANNEL_TO_PROP[shiny_filter.channel_routing[2]]
    armature.dat_pkx_shiny_route_a = _CHANNEL_TO_PROP[shiny_filter.channel_routing[3]]
    armature.dat_pkx_shiny_brightness_r = shiny_filter.brightness[0]
    armature.dat_pkx_shiny_brightness_g = shiny_filter.brightness[1]
    armature.dat_pkx_shiny_brightness_b = shiny_filter.brightness[2]
    armature.dat_pkx_shiny_brightness_a = shiny_filter.brightness[3]


def rebuild_shiny_node_group(armature):
    """Rebuild both shiny node groups from the armature's current property values.

    Called by the property update callbacks in BlenderPlugin.py.
    """
    routing = (
        _PROP_TO_CHANNEL[armature.dat_pkx_shiny_route_r],
        _PROP_TO_CHANNEL[armature.dat_pkx_shiny_route_g],
        _PROP_TO_CHANNEL[armature.dat_pkx_shiny_route_b],
        _PROP_TO_CHANNEL[armature.dat_pkx_shiny_route_a],
    )
    brightness = (
        armature.dat_pkx_shiny_brightness_r,
        armature.dat_pkx_shiny_brightness_g,
        armature.dat_pkx_shiny_brightness_b,
        armature.dat_pkx_shiny_brightness_a,
    )

    route_name = armature.get("dat_pkx_shiny_route_group")
    if route_name and route_name in bpy.data.node_groups:
        populate_shiny_route_node_group(bpy.data.node_groups[route_name], routing)

    bright_name = armature.get("dat_pkx_shiny_bright_group")
    if bright_name and bright_name in bpy.data.node_groups:
        populate_shiny_bright_node_group(bpy.data.node_groups[bright_name], brightness)


# ---------------------------------------------------------------------------
# Vertex color detection (graph-based, works on any material)
# ---------------------------------------------------------------------------

def _find_vertex_color_multiply(nodes, links, shader_node, input_name='Base Color'):
    """Walk backward from a shader input to find a vertex color multiply node.

    Looks for a MixRGB node with blend_type MULTIPLY that has a
    ShaderNodeAttribute (vertex color) as one of its inputs. This
    works on any material — no naming assumptions.

    Args:
        nodes: material node tree nodes.
        links: material node tree links.
        shader_node: the target shader node (Principled BSDF or Emission).
        input_name: name of the shader input to trace from.

    Returns:
        (mix_node, texture_input_socket) if found — mix_node is the vertex
        color multiply, texture_input_socket is the socket on mix_node that
        receives the texture/material color (not the vertex color).
        (None, None) if no vertex color multiply found.
    """
    # Find the link going into the shader input
    target_input = shader_node.inputs.get(input_name)
    if target_input is None:
        return None, None

    current_node = None
    for link in links:
        if link.to_node == shader_node and link.to_socket == target_input:
            current_node = link.from_node
            break

    if current_node is None:
        return None, None

    # Walk backward, checking each node
    visited = set()
    queue = [current_node]
    while queue:
        node = queue.pop(0)
        if id(node) in visited:
            continue
        visited.add(id(node))

        if node.bl_idname == 'ShaderNodeMixRGB' and node.blend_type == 'MULTIPLY':
            # Check if either Color1 or Color2 input comes from a ShaderNodeAttribute
            for input_idx in (1, 2):
                for link in links:
                    if link.to_node == node and link.to_socket == node.inputs[input_idx]:
                        if link.from_node.bl_idname == 'ShaderNodeAttribute':
                            # Found it — the OTHER input is the texture color
                            texture_idx = 2 if input_idx == 1 else 1
                            return node, node.inputs[texture_idx]

        # Continue walking backward through all inputs
        for link in links:
            if link.to_node == node:
                queue.append(link.from_node)

    return None, None


# ---------------------------------------------------------------------------
# Insertion into material node tree
# ---------------------------------------------------------------------------

def insert_shiny_filter(material, route_group, bright_group, armature, logger=None):
    """Insert shiny filter nodes into a material's node tree.

    Places the routing stage BEFORE any vertex color multiply, and the
    brightness stage AFTER it. If no vertex color multiply is found,
    both stages are inserted in sequence at the shader input.

    Args:
        material: bpy.types.Material with use_nodes=True.
        route_group: The ShinyRoute node group.
        bright_group: The ShinyBright node group.
        armature: The armature object with the shiny properties.
        logger: Optional logger for diagnostics.
    """
    if not material.use_nodes:
        if logger:
            logger.debug("    Skipped '%s': use_nodes is False", material.name)
        return

    nodes = material.node_tree.nodes
    links = material.node_tree.links

    # Skip if already applied
    if any(n.name in ('shiny_route_mix', 'shiny_bright_mix') for n in nodes):
        if logger:
            logger.debug("    Skipped '%s': already applied", material.name)
        return

    # Find the shader's color input
    target_node, target_input, is_emission = _find_color_input(nodes)
    if target_node is None:
        if logger:
            logger.debug("    Skipped '%s': no color input found", material.name)
        return

    input_name = 'Color' if is_emission else 'Base Color'

    # Look for vertex color multiply in the chain
    vtx_mult, texture_socket = _find_vertex_color_multiply(
        nodes, links, target_node, input_name)

    if vtx_mult is not None:
        # Insert routing BEFORE the vertex color multiply
        _insert_stage_before(nodes, links, vtx_mult, texture_socket,
                             route_group, 'shiny_route_shader', 'shiny_route_mix', armature)
        # Insert brightness AFTER the vertex color multiply (at the shader input)
        _insert_stage_at_input(nodes, links, target_node, target_input,
                               bright_group, 'shiny_bright_shader', 'shiny_bright_mix', armature)
        if logger:
            logger.debug("    Applied '%s': routing before vtx color, brightness after", material.name)
    else:
        # No vertex colors — insert both stages at the shader input
        _insert_stage_at_input(nodes, links, target_node, target_input,
                               route_group, 'shiny_route_shader', 'shiny_route_mix', armature)
        _insert_stage_at_input(nodes, links, target_node, target_input,
                               bright_group, 'shiny_bright_shader', 'shiny_bright_mix', armature)
        if logger:
            logger.debug("    Applied '%s': routing + brightness (no vtx color)", material.name)

    _auto_layout(nodes, material.node_tree.links)


def _insert_stage_at_input(nodes, links, target_node, target_input,
                            node_group, group_name, mix_name, armature):
    """Insert a shiny stage between a source and a shader input.

    Intercepts the link going into target_input, routes through the
    node group with a driver-controlled mix for toggling.
    """
    # Find existing link to the target input
    source_link = None
    for link in links:
        if link.to_node == target_node and link.to_socket == target_input:
            source_link = link
            break

    if source_link is None:
        default_color = list(target_input.default_value)
        rgb_node = nodes.new('ShaderNodeRGB')
        rgb_node.outputs[0].default_value[:] = default_color
        source_output = rgb_node.outputs[0]
    else:
        source_output = source_link.from_socket
        links.remove(source_link)

    group_node = nodes.new('ShaderNodeGroup')
    group_node.node_tree = node_group
    group_node.name = group_name
    links.new(source_output, group_node.inputs[0])

    mix_node = nodes.new('ShaderNodeMixRGB')
    mix_node.blend_type = 'MIX'
    mix_node.name = mix_name
    mix_node.inputs[0].default_value = 0.0

    links.new(source_output, mix_node.inputs[1])        # Normal path
    links.new(group_node.outputs[0], mix_node.inputs[2]) # Shiny path
    links.new(mix_node.outputs[0], target_input)         # Output to shader

    _add_shiny_driver(mix_node.inputs[0], armature)


def _insert_stage_before(nodes, links, multiply_node, texture_input,
                          node_group, group_name, mix_name, armature):
    """Insert a shiny stage before a vertex color multiply node.

    Intercepts the texture color link going into the multiply node's
    texture input socket, routes through the node group with a mix.
    """
    # Find existing link to the texture input
    source_link = None
    for link in links:
        if link.to_node == multiply_node and link.to_socket == texture_input:
            source_link = link
            break

    if source_link is None:
        return  # No source to intercept

    source_output = source_link.from_socket
    links.remove(source_link)

    group_node = nodes.new('ShaderNodeGroup')
    group_node.node_tree = node_group
    group_node.name = group_name
    links.new(source_output, group_node.inputs[0])

    mix_node = nodes.new('ShaderNodeMixRGB')
    mix_node.blend_type = 'MIX'
    mix_node.name = mix_name
    mix_node.inputs[0].default_value = 0.0

    links.new(source_output, mix_node.inputs[1])          # Normal path
    links.new(group_node.outputs[0], mix_node.inputs[2])   # Shiny path
    links.new(mix_node.outputs[0], texture_input)          # Back to multiply

    _add_shiny_driver(mix_node.inputs[0], armature)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_color_input(nodes):
    """Find the main color input on the output shader.

    Returns (node, input_socket, is_emission) or (None, None, False).
    """
    for node in nodes:
        if node.type == 'BSDF_PRINCIPLED':
            base_color = node.inputs['Base Color']
            if base_color.is_linked:
                return node, base_color, False

    for node in nodes:
        if node.type == 'EMISSION':
            return node, node.inputs['Color'], True

    for node in nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node, node.inputs['Base Color'], False

    return None, None, False


def _add_shiny_driver(factor_input, armature):
    """Add a driver to a mix node's Factor input driven by armature.dat_pkx_shiny."""
    factor_input.default_value = 0.0

    driver_data = factor_input.driver_add("default_value")
    driver = driver_data.driver
    driver.type = 'AVERAGE'

    var = driver.variables.new()
    var.name = "shiny"
    var.type = 'SINGLE_PROP'
    target = var.targets[0]
    target.id_type = 'OBJECT'
    target.id = armature
    target.data_path = 'dat_pkx_shiny'


def _auto_layout(nodes, links, output_type='OUTPUT_MATERIAL'):
    """Arrange shader nodes left-to-right via topological sort from output."""
    NODE_WIDTH = 300
    NODE_HEIGHT = 200

    output = None
    for node in nodes:
        if node.type == output_type:
            output = node
            break
    if output is None:
        return

    inputs_of = {}
    for link in links:
        target = link.to_node
        source = link.from_node
        if target not in inputs_of:
            inputs_of[target] = []
        if source not in inputs_of[target]:
            inputs_of[target].append(source)

    column_of = {output: 0}
    queue = [output]
    while queue:
        node = queue.pop(0)
        col = column_of[node]
        for source in inputs_of.get(node, []):
            new_col = col + 1
            if source not in column_of or column_of[source] < new_col:
                column_of[source] = new_col
                queue.append(source)

    max_col = max(column_of.values()) if column_of else 0
    for node in nodes:
        if node not in column_of:
            max_col += 1
            column_of[node] = max_col

    columns = {}
    for node, col in column_of.items():
        columns.setdefault(col, []).append(node)

    for col in columns:
        columns[col].sort(key=lambda n: n.name)

    max_column = max(columns.keys()) if columns else 0
    for col, col_nodes in columns.items():
        x = (max_column - col) * NODE_WIDTH
        for i, node in enumerate(col_nodes):
            y = -i * NODE_HEIGHT
            node.location = (x, y)


def _auto_layout_node_group(nodes, links):
    """Arrange nodes inside a node group."""
    _auto_layout(nodes, links, output_type='GROUP_OUTPUT')
