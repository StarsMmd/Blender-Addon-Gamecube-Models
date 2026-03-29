"""Standalone Blender script: Add shiny filter to the selected armature.

Run this from Blender's Scripting panel (Text Editor > Run Script) with an
armature selected. It creates a ShinyFilter node group with no-op (identity)
parameters and inserts it into every material on the armature's child meshes.

The Shiny Variant panel in Object Properties will appear on the armature,
allowing live editing of all 8 shiny parameters (4 channel routing + 4 brightness).

Requires the DAT plugin addon to be enabled (for the registered shiny properties).
"""
import bpy
from enum import Enum


# ---------------------------------------------------------------------------
# Minimal ShinyChannel enum (mirrors shared/IR/enums.py without import dep)
# ---------------------------------------------------------------------------

class ShinyChannel(Enum):
    RED = 0
    GREEN = 1
    BLUE = 2
    ALPHA = 3


# ---------------------------------------------------------------------------
# Node group construction (mirrors shiny_filter.py logic)
# ---------------------------------------------------------------------------

def _populate_shiny_node_group(group, routing, brightness):
    """Populate a node group with the shiny filter nodes."""
    nodes = group.nodes
    links = group.links
    nodes.clear()

    group_in = nodes.new('NodeGroupInput')
    group_out = nodes.new('NodeGroupOutput')

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
        has_alpha_socket = len(group.interface.items_tree) > 2
        if not has_alpha_socket:
            group.interface.new_socket('Alpha', in_out='INPUT', socket_type='NodeSocketFloat')
        channel_sources[ShinyChannel.ALPHA] = group_in.outputs[1]
    else:
        items = list(group.interface.items_tree)
        if len(items) > 2:
            for item in items:
                if item.name == 'Alpha' and item.in_out == 'INPUT':
                    group.interface.remove(item)
                    break
        channel_sources[ShinyChannel.ALPHA] = None

    scaled_channels = []
    for i in range(3):
        source_channel = routing[i]
        source_socket = channel_sources[source_channel]
        brightness_multiplier = brightness[i] + 1.0

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


def _find_color_input(nodes):
    """Find the main color input on the output shader."""
    for node in nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node, node.inputs['Base Color']
    for node in nodes:
        if node.type == 'EMISSION':
            return node, node.inputs['Color']
    return None, None


def _insert_shiny_filter(material, node_group, armature):
    """Insert the shiny filter node group into a material's node tree."""
    if not material.use_nodes:
        return

    nodes = material.node_tree.nodes
    links = material.node_tree.links

    # Skip if already has a shiny filter
    for node in nodes:
        if node.name == 'shiny_filter_shader':
            return

    target_node, target_input = _find_color_input(nodes)
    if target_node is None:
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
    links.new(mix_node.outputs[0], target_input)

    # Driver: mix factor driven by armature.dat_shiny
    driver_data = mix_node.inputs[0].driver_add("default_value")
    driver = driver_data.driver
    driver.type = 'AVERAGE'
    var = driver.variables.new()
    var.name = "shiny"
    var.type = 'SINGLE_PROP'
    target = var.targets[0]
    target.id_type = 'OBJECT'
    target.id = armature
    target.data_path = 'dat_shiny'


# ---------------------------------------------------------------------------
# Main script
# ---------------------------------------------------------------------------

def main():
    armature = bpy.context.active_object

    if armature is None or armature.type != 'ARMATURE':
        raise ValueError("Select an armature object before running this script.")

    if armature.get("dat_has_shiny"):
        raise ValueError("This armature already has a shiny filter. "
                         "Edit the parameters in the Shiny Variant panel instead.")

    # Verify the addon is enabled (shiny properties must be registered)
    if not hasattr(armature, 'dat_shiny'):
        raise ValueError("The DAT plugin addon must be enabled for shiny properties to work. "
                         "Enable it in Edit > Preferences > Extensions.")

    model_name = armature.name
    group_name = "ShinyFilter_%s" % model_name

    # No-op parameters: identity routing, zero brightness
    noop_routing = (ShinyChannel.RED, ShinyChannel.GREEN, ShinyChannel.BLUE, ShinyChannel.ALPHA)
    noop_brightness = (0.0, 0.0, 0.0, 0.0)

    # Create the node group
    group = bpy.data.node_groups.new(group_name, 'ShaderNodeTree')
    group.interface.new_socket('Color', in_out='INPUT', socket_type='NodeSocketColor')
    group.interface.new_socket('Color', in_out='OUTPUT', socket_type='NodeSocketColor')
    _populate_shiny_node_group(group, noop_routing, noop_brightness)

    # Set up armature properties
    armature["dat_has_shiny"] = True
    armature["dat_shiny_group"] = group_name
    armature.dat_shiny = False
    armature.dat_shiny_route_r = 'RED'
    armature.dat_shiny_route_g = 'GREEN'
    armature.dat_shiny_route_b = 'BLUE'
    armature.dat_shiny_route_a = 'ALPHA'
    armature.dat_shiny_brightness_r = 0.0
    armature.dat_shiny_brightness_g = 0.0
    armature.dat_shiny_brightness_b = 0.0
    armature.dat_shiny_brightness_a = 0.0

    # Insert into all child mesh materials
    count = 0
    for child in armature.children:
        if child.type != 'MESH':
            continue
        for slot in child.material_slots:
            if slot.material:
                _insert_shiny_filter(slot.material, group, armature)
                count += 1

    print("Added shiny filter to %d material(s) on '%s'." % (count, model_name))
    print("Use the Shiny Variant panel in Object Properties to adjust parameters.")


main()
