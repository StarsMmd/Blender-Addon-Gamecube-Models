"""Build and insert shiny color filter shader nodes.

Creates two node groups for the PKX shiny color transformation:
  - ShinyRoute: channel routing (swizzle) applied at the shader input
  - ShinyBright: brightness scaling applied at the shader input

Both stages are applied uniformly to ALL materials on the model, matching
the game's behavior (GSmodelEnableColorSwap + GSmodelEnableModulation
iterate all materials globally). There is no per-material selectivity.

Alpha brightness is forced to maximum by the game (byte 0x13 set to 0xFF
before GSmodelEnableModulation is called). Our brightness shader only
scales RGB channels; alpha passes through unchanged.

The node groups are rebuilt whenever the dat_pkx_shiny toggle is activated,
reading the current values from dat_pkx_shiny_route and dat_pkx_shiny_brightness
custom properties on the armature.
"""
import bpy

try:
    from ....shared.IR.enums import ShinyChannel
except (ImportError, SystemError):
    from shared.IR.enums import ShinyChannel

# Fixed node group names — independent of armature/model names
SHINY_ROUTE_GROUP = "DATPlugin_ShinyRoute"
SHINY_BRIGHT_GROUP = "DATPlugin_ShinyBright"


# ---------------------------------------------------------------------------
# Node group construction
# ---------------------------------------------------------------------------

def build_shiny_route_node_group(routing, name):
    """Create a node group that performs channel routing (swizzle).

    Args:
        routing: tuple of 4 ints (0-3) — which source channel maps to R,G,B,A output.
        name: Name for the node group (e.g. "ShinyRoute_model_name").

    Returns:
        bpy.types.ShaderNodeTree (the node group).
    """
    group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    group.interface.new_socket('Color', in_out='INPUT', socket_type='NodeSocketColor')
    group.interface.new_socket('Color', in_out='OUTPUT', socket_type='NodeSocketColor')

    _populate_route_group(group, routing)
    return group


def build_shiny_bright_node_group(brightness, name):
    """Create a node group that performs per-channel brightness scaling.

    Args:
        brightness: tuple of 3 floats [-1.0, 1.0] for R,G,B brightness.
        name: Name for the node group (e.g. "ShinyBright_model_name").

    Returns:
        bpy.types.ShaderNodeTree (the node group).
    """
    group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    group.interface.new_socket('Color', in_out='INPUT', socket_type='NodeSocketColor')
    group.interface.new_socket('Color', in_out='OUTPUT', socket_type='NodeSocketColor')

    _populate_bright_group(group, brightness)
    return group


def _populate_route_group(group, routing):
    """Populate a node group with channel routing nodes.

    Clears existing nodes and rebuilds from the routing values.
    Only RGB channels are routed — the game's GXSetTevSwapModeTable remaps
    R/G/B/A but alpha routing is always identity (route_a=3) and has no
    visual effect since brightness alpha is forced to 0xFF.
    """
    nodes = group.nodes
    links = group.links
    nodes.clear()

    # Remove any leftover Alpha input socket from older versions
    for item in list(group.interface.items_tree):
        if item.name == 'Alpha' and item.in_out == 'INPUT':
            group.interface.remove(item)
            break

    group_in = nodes.new('NodeGroupInput')
    group_out = nodes.new('NodeGroupOutput')

    # Separate → route → combine
    separate = nodes.new('ShaderNodeSeparateColor')
    separate.mode = 'RGB'
    links.new(group_in.outputs[0], separate.inputs[0])

    channel_sources = {
        0: separate.outputs[0],  # Red
        1: separate.outputs[1],  # Green
        2: separate.outputs[2],  # Blue
    }

    # Route each RGB output channel (values 0-2 only; 3=Alpha is ignored)
    combine = nodes.new('ShaderNodeCombineColor')
    combine.mode = 'RGB'
    for i in range(3):
        source_ch = routing[i]
        if source_ch in channel_sources:
            links.new(channel_sources[source_ch], combine.inputs[i])
        else:
            # Route value 3 (Alpha) or out-of-range — use zero
            value = nodes.new('ShaderNodeValue')
            value.outputs[0].default_value = 0.0
            links.new(value.outputs[0], combine.inputs[i])

    links.new(combine.outputs[0], group_out.inputs[0])
    _auto_layout_node_group(nodes, links)


def _populate_bright_group(group, brightness):
    """Populate a node group with per-channel brightness scaling.

    brightness: tuple of 3 floats [-1, 1] for R, G, B.
    Alpha is NOT scaled (forced to max by the game).
    Multiply factor = brightness + 1.0 → range [0.0, 2.0].

    The GameCube applies brightness in sRGB/gamma space (no linear pipeline),
    but Blender's shader nodes operate in linear space. To match the game's
    visual output, we convert linear→sRGB before multiplying, then sRGB→linear
    after: Gamma(1/2.2) → Multiply → Gamma(2.2).
    """
    nodes = group.nodes
    links = group.links
    nodes.clear()

    group_in = nodes.new('NodeGroupInput')
    group_out = nodes.new('NodeGroupOutput')

    # Linear → sRGB (so brightness multiply matches the game's gamma-space math)
    to_srgb = nodes.new('ShaderNodeGamma')
    to_srgb.name = 'LinearToSRGB'
    to_srgb.inputs[1].default_value = 1.0 / 2.2
    links.new(group_in.outputs[0], to_srgb.inputs[0])

    separate = nodes.new('ShaderNodeSeparateColor')
    separate.mode = 'RGB'
    links.new(to_srgb.outputs[0], separate.inputs[0])

    channel_names = ['R', 'G', 'B']
    scaled = []
    for i in range(3):
        mult = nodes.new('ShaderNodeMath')
        mult.operation = 'MULTIPLY'
        mult.name = 'Brightness_%s' % channel_names[i]
        links.new(separate.outputs[i], mult.inputs[0])
        mult.inputs[1].default_value = brightness[i] + 1.0  # [-1,1] → [0,2]
        scaled.append(mult.outputs[0])

    combine = nodes.new('ShaderNodeCombineColor')
    combine.mode = 'RGB'
    links.new(scaled[0], combine.inputs[0])
    links.new(scaled[1], combine.inputs[1])
    links.new(scaled[2], combine.inputs[2])

    # sRGB → Linear (back to Blender's working space)
    to_linear = nodes.new('ShaderNodeGamma')
    to_linear.name = 'SRGBToLinear'
    to_linear.inputs[1].default_value = 2.2
    links.new(combine.outputs[0], to_linear.inputs[0])

    links.new(to_linear.outputs[0], group_out.inputs[0])
    _auto_layout_node_group(nodes, links)


# ---------------------------------------------------------------------------
# Property setup and rebuild
# ---------------------------------------------------------------------------

def setup_shiny_properties(armature, route, brightness):
    """Initialize shiny metadata on the armature.

    Sets the registered bpy.props (which drive the UI and shader nodes).
    Shiny data existence is derived from whether route/brightness differ
    from identity — no stored flag needed.

    Args:
        armature: The Blender armature object.
        route: list of 4 ints (0-3) — channel routing.
        brightness: list of 3 floats [-1, 1] — RGB brightness.
    """
    # Set registered properties (these are the source of truth for UI + shaders)
    armature.dat_pkx_shiny = False
    armature.dat_pkx_shiny_route_r = str(route[0])
    armature.dat_pkx_shiny_route_g = str(route[1])
    armature.dat_pkx_shiny_route_b = str(route[2])
    armature.dat_pkx_shiny_route_a = str(route[3])
    armature.dat_pkx_shiny_brightness_r = brightness[0]
    armature.dat_pkx_shiny_brightness_g = brightness[1]
    armature.dat_pkx_shiny_brightness_b = brightness[2]


def rebuild_shiny_node_group(armature):
    """Rebuild both shiny node groups from the armature's registered properties.

    Called when the dat_pkx_shiny toggle or any routing/brightness property changes.
    """
    # Read from registered properties (already synced to custom props by callback)
    try:
        route = [
            int(armature.dat_pkx_shiny_route_r),
            int(armature.dat_pkx_shiny_route_g),
            int(armature.dat_pkx_shiny_route_b),
            int(armature.dat_pkx_shiny_route_a),
        ]
        brightness = [
            armature.dat_pkx_shiny_brightness_r,
            armature.dat_pkx_shiny_brightness_g,
            armature.dat_pkx_shiny_brightness_b,
        ]
    except AttributeError:
        # Fallback to custom properties if registered props not available
        route = list(armature.get("dat_pkx_shiny_route", [0, 1, 2, 3]))
        brightness = list(armature.get("dat_pkx_shiny_brightness", [0.0, 0.0, 0.0]))

    while len(route) < 4:
        route.append(len(route))
    while len(brightness) < 3:
        brightness.append(0.0)

    if SHINY_ROUTE_GROUP in bpy.data.node_groups:
        _populate_route_group(bpy.data.node_groups[SHINY_ROUTE_GROUP], route)

    if SHINY_BRIGHT_GROUP in bpy.data.node_groups:
        _populate_bright_group(bpy.data.node_groups[SHINY_BRIGHT_GROUP], brightness)


# ---------------------------------------------------------------------------
# Insertion into material node tree
# ---------------------------------------------------------------------------

def insert_shiny_filter(material, route_group, bright_group, armature, logger=None):
    """Insert shiny filter nodes into a material's node tree.

    Both stages are inserted at the shader input — the game applies
    shiny globally to all materials (no per-material selectivity).

    Args:
        material: bpy.types.Material with use_nodes=True.
        route_group: The ShinyRoute node group.
        bright_group: The ShinyBright node group.
        armature: The armature object with the shiny toggle.
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

    target_node, target_input, is_emission = _find_color_input(nodes)
    if target_node is None:
        if logger:
            logger.debug("    Skipped '%s': no color input found", material.name)
        return

    # Insert both stages at the shader input
    _insert_stage_at_input(nodes, links, target_node, target_input,
                           route_group, 'shiny_route_shader', 'shiny_route_mix', armature)
    _insert_stage_at_input(nodes, links, target_node, target_input,
                           bright_group, 'shiny_bright_shader', 'shiny_bright_mix', armature)

    if logger:
        logger.debug("    Applied shiny to '%s'", material.name)

    _auto_layout(nodes, material.node_tree.links)


def _insert_stage_at_input(nodes, links, target_node, target_input,
                            node_group, group_name, mix_name, armature):
    """Insert a shiny stage between a source and a shader input."""
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
    links.new(mix_node.outputs[0], target_input)

    _add_shiny_driver(mix_node.inputs[0], armature)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_color_input(nodes):
    """Find the main color input on the output shader."""
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
    _auto_layout(nodes, links, output_type='GROUP_OUTPUT')
