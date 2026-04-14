"""Standalone Blender script: Add shiny filter to the selected armature.

Run this from Blender's Scripting panel (Text Editor > Run Script) with an
armature selected. It creates ShinyRoute and ShinyBright node groups and
inserts them into every material on the armature's child meshes. Uses
whatever shiny params are already on the armature (from PKX import,
prepare_for_export, or user edits) — defaults to identity if unset.

Materials that already have shiny nodes are skipped, so this is safe to
run multiple times or after prepare_for_export.

Edit the shiny route/brightness in the PKX Metadata panel to change the
appearance. Toggle dat_pkx_shiny to preview the effect.

Requires the DAT plugin addon to be enabled.

This script is fully standalone — no imports from the plugin codebase.
"""
import bpy

SHINY_ROUTE_GROUP = "DATPlugin_ShinyRoute"
SHINY_BRIGHT_GROUP = "DATPlugin_ShinyBright"


# ---------------------------------------------------------------------------
# Auto-layout helpers
# ---------------------------------------------------------------------------

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
        inputs_of.setdefault(link.to_node, [])
        if link.from_node not in inputs_of[link.to_node]:
            inputs_of[link.to_node].append(link.from_node)

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
            node.location = (x, -i * NODE_HEIGHT)


def _auto_layout_node_group(nodes, links):
    _auto_layout(nodes, links, output_type='GROUP_OUTPUT')


# ---------------------------------------------------------------------------
# Node group construction
# ---------------------------------------------------------------------------

def _build_route_group(routing, name):
    """Create/rebuild the ShinyRoute node group (channel swizzle)."""
    group = bpy.data.node_groups.get(name)
    if group is None:
        group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
        group.interface.new_socket('Color', in_out='INPUT', socket_type='NodeSocketColor')
        group.interface.new_socket('Color', in_out='OUTPUT', socket_type='NodeSocketColor')

    nodes = group.nodes
    links = group.links
    nodes.clear()

    group_in = nodes.new('NodeGroupInput')
    group_out = nodes.new('NodeGroupOutput')

    separate = nodes.new('ShaderNodeSeparateColor')
    separate.mode = 'RGB'
    links.new(group_in.outputs[0], separate.inputs[0])

    channel_sources = {0: separate.outputs[0], 1: separate.outputs[1], 2: separate.outputs[2]}

    combine = nodes.new('ShaderNodeCombineColor')
    combine.mode = 'RGB'
    for i in range(3):
        src = routing[i]
        if src in channel_sources:
            links.new(channel_sources[src], combine.inputs[i])
        else:
            value = nodes.new('ShaderNodeValue')
            value.outputs[0].default_value = 0.0
            links.new(value.outputs[0], combine.inputs[i])

    links.new(combine.outputs[0], group_out.inputs[0])
    _auto_layout_node_group(nodes, links)
    return group


def _build_bright_group(brightness, name):
    """Create/rebuild the ShinyBright node group (per-channel brightness)."""
    group = bpy.data.node_groups.get(name)
    if group is None:
        group = bpy.data.node_groups.new(name, 'ShaderNodeTree')
        group.interface.new_socket('Color', in_out='INPUT', socket_type='NodeSocketColor')
        group.interface.new_socket('Color', in_out='OUTPUT', socket_type='NodeSocketColor')

    nodes = group.nodes
    links = group.links
    nodes.clear()

    group_in = nodes.new('NodeGroupInput')
    group_out = nodes.new('NodeGroupOutput')

    # Linear → sRGB (game multiplies in gamma space)
    to_srgb = nodes.new('ShaderNodeGamma')
    to_srgb.inputs[1].default_value = 1.0 / 2.2
    links.new(group_in.outputs[0], to_srgb.inputs[0])

    separate = nodes.new('ShaderNodeSeparateColor')
    separate.mode = 'RGB'
    links.new(to_srgb.outputs[0], separate.inputs[0])

    scaled = []
    for i, ch in enumerate(['R', 'G', 'B']):
        mult = nodes.new('ShaderNodeMath')
        mult.operation = 'MULTIPLY'
        mult.name = 'Brightness_%s' % ch
        links.new(separate.outputs[i], mult.inputs[0])
        mult.inputs[1].default_value = brightness[i] + 1.0
        scaled.append(mult.outputs[0])

    combine = nodes.new('ShaderNodeCombineColor')
    combine.mode = 'RGB'
    for i in range(3):
        links.new(scaled[i], combine.inputs[i])

    # sRGB → Linear
    to_linear = nodes.new('ShaderNodeGamma')
    to_linear.inputs[1].default_value = 2.2
    links.new(combine.outputs[0], to_linear.inputs[0])

    links.new(to_linear.outputs[0], group_out.inputs[0])
    _auto_layout_node_group(nodes, links)
    return group


# ---------------------------------------------------------------------------
# Insert into materials
# ---------------------------------------------------------------------------

def _find_color_input(nodes):
    """Find the main color input on the output shader."""
    for node in nodes:
        if node.type == 'BSDF_PRINCIPLED':
            base_color = node.inputs['Base Color']
            if base_color.is_linked:
                return node, base_color
    for node in nodes:
        if node.type == 'EMISSION':
            return node, node.inputs['Color']
    for node in nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node, node.inputs['Base Color']
    return None, None


def _has_no_texture_in_color_chain(target_input):
    """True when no ShaderNodeTexImage is reachable from the shader color input.

    The in-game shiny color swap operates on GX texture swap tables; a
    material whose TEV chain has no texture sample has nothing to swizzle,
    and the brightness modulation on a constant-colour chain reads as
    untouched compared to the saturated re-tint textured materials get.
    Skip these materials so the shader-side simulation matches.

    An unlinked target input (default-valued Base Color) is also treated
    as "no texture" — still a pure constant-colour chain.
    """
    if not target_input.is_linked:
        return True
    visited = set()
    stack = [target_input]
    while stack:
        sock = stack.pop()
        for link in sock.links:
            node = link.from_node
            if id(node) in visited:
                continue
            visited.add(id(node))
            if node.type == 'TEX_IMAGE':
                return False
            for inp in node.inputs:
                if inp.is_linked:
                    stack.append(inp)
    return True


def _add_driver(factor_input, armature):
    """Add a driver to a mix node's Factor driven by armature.dat_pkx_shiny."""
    factor_input.default_value = 0.0
    driver_data = factor_input.driver_add("default_value")
    driver = driver_data.driver
    driver.type = 'AVERAGE'
    var = driver.variables.new()
    var.name = "shiny"
    var.type = 'SINGLE_PROP'
    var.targets[0].id_type = 'OBJECT'
    var.targets[0].id = armature
    var.targets[0].data_path = 'dat_pkx_shiny'


def _insert_stage(nodes, links, target_node, target_input,
                  node_group, group_name, mix_name, armature):
    """Insert a shiny stage between a source and a shader input."""
    source_link = None
    for link in links:
        if link.to_node == target_node and link.to_socket == target_input:
            source_link = link
            break

    if source_link is None:
        rgb_node = nodes.new('ShaderNodeRGB')
        rgb_node.outputs[0].default_value[:] = list(target_input.default_value)
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
    links.new(source_output, mix_node.inputs[1])
    links.new(group_node.outputs[0], mix_node.inputs[2])
    links.new(mix_node.outputs[0], target_input)

    _add_driver(mix_node.inputs[0], armature)


def insert_shiny_filter(material, route_group, bright_group, armature):
    """Insert shiny filter nodes into a material."""
    if not material.use_nodes:
        return
    nodes = material.node_tree.nodes
    links = material.node_tree.links

    if any(n.name in ('shiny_route_mix', 'shiny_bright_mix') for n in nodes):
        return

    target_node, target_input = _find_color_input(nodes)
    if target_node is None:
        return

    if _has_no_texture_in_color_chain(target_input):
        return

    _insert_stage(nodes, links, target_node, target_input,
                  route_group, 'shiny_route_shader', 'shiny_route_mix', armature)
    _insert_stage(nodes, links, target_node, target_input,
                  bright_group, 'shiny_bright_shader', 'shiny_bright_mix', armature)

    _auto_layout(nodes, material.node_tree.links)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    armature = bpy.context.active_object

    if armature is None or armature.type != 'ARMATURE':
        raise ValueError("Select an armature object before running this script.")

    if not hasattr(armature, 'dat_pkx_shiny'):
        raise ValueError("The DAT plugin addon must be enabled for shiny properties to work. "
                         "Enable it in Edit > Preferences > Extensions.")

    # Read current shiny params from registered properties (always present
    # when the addon is enabled — defaults are identity/neutral).
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

    route_group = _build_route_group(route, SHINY_ROUTE_GROUP)
    bright_group = _build_bright_group(brightness, SHINY_BRIGHT_GROUP)

    count = 0
    for child in armature.children:
        if child.type != 'MESH':
            continue
        for slot in child.material_slots:
            if slot.material:
                insert_shiny_filter(slot.material, route_group, bright_group, armature)
                count += 1

    print("Added shiny filter to %d material(s) on '%s'." % (count, armature.name))
    print("Toggle dat_pkx_shiny in the PKX Metadata panel to preview.")


main()
