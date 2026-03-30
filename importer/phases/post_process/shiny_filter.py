"""Build and insert shiny color filter shader nodes.

Creates a node group that applies the PKX shiny color transformation
(channel routing + brightness scaling) and inserts it into material
node trees with a driver-controlled mix for runtime toggling.

The node group is rebuilt whenever any shiny parameter property changes,
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


def populate_shiny_node_group(group, routing, brightness):
    """Populate (or repopulate) a node group with the shiny filter nodes.

    Clears any existing nodes and rebuilds from scratch. Since all material
    group node instances reference this group, changes propagate automatically.

    Args:
        group: bpy.types.ShaderNodeTree (the node group to populate).
        routing: tuple of 4 ShinyChannel values (R, G, B, A output mapping).
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

    needs_alpha_input = any(
        routing[i] == ShinyChannel.ALPHA for i in range(3)
    )

    channel_sources = {
        ShinyChannel.RED: separate.outputs[0],
        ShinyChannel.GREEN: separate.outputs[1],
        ShinyChannel.BLUE: separate.outputs[2],
    }

    if needs_alpha_input:
        # Add Alpha input socket if not already present
        has_alpha_socket = len(group.interface.items_tree) > 2
        if not has_alpha_socket:
            group.interface.new_socket('Alpha', in_out='INPUT', socket_type='NodeSocketFloat')
        alpha_input = group_in.outputs[1]
        channel_sources[ShinyChannel.ALPHA] = alpha_input
    else:
        # Remove Alpha socket if present (more than 2 interface items = input + output + alpha)
        items = list(group.interface.items_tree)
        if len(items) > 2:
            for item in items:
                if item.name == 'Alpha' and item.in_out == 'INPUT':
                    group.interface.remove(item)
                    break
        channel_sources[ShinyChannel.ALPHA] = None

    # For each RGB output channel: route source → multiply by brightness
    scaled_channels = []
    for i in range(3):
        source_channel = routing[i]
        source_socket = channel_sources[source_channel]
        brightness_multiplier = brightness[i] + 1.0  # [-1,1] → [0,2]

        if source_socket is not None:
            mult = nodes.new('ShaderNodeMath')
            mult.operation = 'MULTIPLY'
            mult.name = 'Brightness_%s' % ['R', 'G', 'B'][i]
            links.new(source_socket, mult.inputs[0])
            mult.inputs[1].default_value = brightness_multiplier
            scaled_channels.append(mult.outputs[0])
        else:
            value = nodes.new('ShaderNodeValue')
            value.outputs[0].default_value = 0.0
            scaled_channels.append(value.outputs[0])

    combine = nodes.new('ShaderNodeCombineColor')
    combine.mode = 'RGB'
    links.new(scaled_channels[0], combine.inputs[0])
    links.new(scaled_channels[1], combine.inputs[1])
    links.new(scaled_channels[2], combine.inputs[2])

    links.new(combine.outputs[0], group_out.inputs[0])

    _auto_layout_node_group(nodes, links)


def build_shiny_node_group(shiny_filter, name):
    """Create a reusable node group implementing the shiny color transformation.

    Args:
        shiny_filter: IRShinyFilter with channel_routing and brightness.
        name: Name for the node group (e.g. "ShinyFilter_model_name").

    Returns:
        bpy.types.ShaderNodeTree (the node group).
    """
    group = bpy.data.node_groups.new(name, 'ShaderNodeTree')

    group.interface.new_socket('Color', in_out='INPUT', socket_type='NodeSocketColor')
    group.interface.new_socket('Color', in_out='OUTPUT', socket_type='NodeSocketColor')

    populate_shiny_node_group(group, shiny_filter.channel_routing, shiny_filter.brightness)

    return group


def setup_shiny_properties(armature, shiny_filter, group_name):
    """Initialize all shiny properties on the armature from an IRShinyFilter.

    The properties themselves are registered on bpy.types.Object in BlenderPlugin.register().
    This sets initial values and stores the node group name for live rebuilding.

    Args:
        armature: The Blender armature object.
        shiny_filter: IRShinyFilter with channel_routing and brightness.
        group_name: Name of the ShinyFilter node group (for rebuilding).
    """
    armature["dat_has_shiny"] = True
    armature["dat_shiny_group"] = group_name

    armature.dat_shiny = False
    armature.dat_shiny_route_r = _CHANNEL_TO_PROP[shiny_filter.channel_routing[0]]
    armature.dat_shiny_route_g = _CHANNEL_TO_PROP[shiny_filter.channel_routing[1]]
    armature.dat_shiny_route_b = _CHANNEL_TO_PROP[shiny_filter.channel_routing[2]]
    armature.dat_shiny_route_a = _CHANNEL_TO_PROP[shiny_filter.channel_routing[3]]
    armature.dat_shiny_brightness_r = shiny_filter.brightness[0]
    armature.dat_shiny_brightness_g = shiny_filter.brightness[1]
    armature.dat_shiny_brightness_b = shiny_filter.brightness[2]
    armature.dat_shiny_brightness_a = shiny_filter.brightness[3]


def rebuild_shiny_node_group(armature):
    """Rebuild the shiny node group from the armature's current property values.

    Called by the property update callbacks in BlenderPlugin.py.
    """
    group_name = armature.get("dat_shiny_group")
    if not group_name or group_name not in bpy.data.node_groups:
        return

    group = bpy.data.node_groups[group_name]

    routing = (
        _PROP_TO_CHANNEL[armature.dat_shiny_route_r],
        _PROP_TO_CHANNEL[armature.dat_shiny_route_g],
        _PROP_TO_CHANNEL[armature.dat_shiny_route_b],
        _PROP_TO_CHANNEL[armature.dat_shiny_route_a],
    )
    brightness = (
        armature.dat_shiny_brightness_r,
        armature.dat_shiny_brightness_g,
        armature.dat_shiny_brightness_b,
        armature.dat_shiny_brightness_a,
    )

    populate_shiny_node_group(group, routing, brightness)


def insert_shiny_filter(material, node_group, armature, logger=None):
    """Insert the shiny filter node group into a material's node tree.

    Finds the color source feeding into the main shader and interposes a Mix node
    controlled by a driver on armature.dat_shiny to blend between normal and shiny.

    Args:
        material: bpy.types.Material with use_nodes=True.
        node_group: The ShinyFilter node group (from build_shiny_node_group).
        armature: The armature object with the shiny properties.
        logger: Optional logger for diagnostics.
    """
    if not material.use_nodes:
        if logger:
            logger.debug("    Skipped '%s': use_nodes is False", material.name)
        return

    nodes = material.node_tree.nodes

    # Skip if already applied
    if 'shiny_filter_mix' in nodes or 'shiny_filter_shader' in nodes:
        if logger:
            logger.debug("    Skipped '%s': already applied", material.name)
        return
    links = material.node_tree.links

    target_node, target_input, is_emission = _find_color_input(nodes)
    if target_node is None:
        if logger:
            node_types = [n.type for n in nodes]
            logger.debug("    Skipped '%s': no color input found, node types: %s", material.name, node_types)
        return

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
    group_node.name = 'shiny_filter_shader'

    links.new(source_output, group_node.inputs[0])

    if len(group_node.inputs) > 1:
        group_node.inputs[1].default_value = 1.0

    mix_node = nodes.new('ShaderNodeMixRGB')
    mix_node.blend_type = 'MIX'
    mix_node.name = 'shiny_filter_mix'
    mix_node.inputs[0].default_value = 0.0

    links.new(source_output, mix_node.inputs[1])
    links.new(group_node.outputs[0], mix_node.inputs[2])

    # Gamma node: linearize the shiny output (sRGB → linear) so Blender's
    # scene-linear pipeline produces accurate colors.
    gamma_node = nodes.new('ShaderNodeGamma')
    gamma_node.name = 'shiny_filter_gamma'
    gamma_node.inputs[1].default_value = 2.2

    links.new(mix_node.outputs[0], gamma_node.inputs[0])
    links.new(gamma_node.outputs[0], target_input)

    _add_shiny_driver(mix_node.inputs[0], armature)

    _auto_layout(nodes, material.node_tree.links)


def _find_color_input(nodes):
    """Find the main color input on the output shader.

    Checks Principled BSDF first, but only if its Base Color has an incoming
    link. Unlit materials (e.g. legacy importer) set Base Color to black and
    route the actual color through an Emission node instead.

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

    # Fallback: Principled BSDF with no link (solid color)
    for node in nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node, node.inputs['Base Color'], False

    return None, None, False


def _add_shiny_driver(factor_input, armature):
    """Add a driver to a mix node's Factor input driven by armature.dat_shiny."""
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
    target.data_path = 'dat_shiny'


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
    """Arrange nodes inside a node group (uses GROUP_OUTPUT as root)."""
    _auto_layout(nodes, links, output_type='GROUP_OUTPUT')
