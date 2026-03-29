"""Build and insert shiny color filter shader nodes.

Creates a node group that applies the PKX shiny color transformation
(channel routing + brightness scaling) and inserts it into material
node trees with a driver-controlled mix for runtime toggling.
"""
import bpy

try:
    from .....shared.IR.enums import ShinyChannel
except (ImportError, SystemError):
    from shared.IR.enums import ShinyChannel

# Map ShinyChannel enum to Separate Color output index
_CHANNEL_OUTPUT_INDEX = {
    ShinyChannel.RED: 0,
    ShinyChannel.GREEN: 1,
    ShinyChannel.BLUE: 2,
    ShinyChannel.ALPHA: 3,
}


def build_shiny_node_group(shiny_filter, name):
    """Create a reusable node group implementing the shiny color transformation.

    The group takes an RGBA color input, applies channel routing (Color1)
    and brightness scaling (Color2) to RGB channels, and passes alpha through.

    Args:
        shiny_filter: IRShinyFilter with channel_routing and brightness.
        name: Name for the node group (e.g. "ShinyFilter_model_name").

    Returns:
        bpy.types.ShaderNodeTree (the node group).
    """
    group = bpy.data.node_groups.new(name, 'ShaderNodeTree')

    # Create group interface sockets
    group.interface.new_socket('Color', in_out='INPUT', socket_type='NodeSocketColor')
    group.interface.new_socket('Color', in_out='OUTPUT', socket_type='NodeSocketColor')

    nodes = group.nodes
    links = group.links

    # Group input/output
    group_in = nodes.new('NodeGroupInput')
    group_out = nodes.new('NodeGroupOutput')

    # Separate Color → R, G, B, A
    separate = nodes.new('ShaderNodeSeparateColor')
    separate.mode = 'RGB'
    links.new(group_in.outputs[0], separate.inputs[0])

    # Channel routing + brightness for R, G, B
    # separate.outputs: 0=Red, 1=Green, 2=Blue, 3=Alpha (Alpha via separate alpha below)

    # We need alpha from the input too — Separate Color in RGB mode gives R, G, B
    # but not Alpha directly. Use a Separate XYZ won't work. Let's use Separate Color
    # which in Blender 4.x gives R, G, B outputs (indices 0, 1, 2).
    # For alpha, we need a separate node.
    separate_alpha = nodes.new('ShaderNodeSeparateColor')
    separate_alpha.mode = 'RGB'
    links.new(group_in.outputs[0], separate_alpha.inputs[0])

    # Actually, ShaderNodeSeparateColor in RGB mode gives 3 outputs: Red, Green, Blue.
    # Alpha is not available as a separate output. We need ShaderNodeSeparateColor
    # doesn't expose alpha. Let's use the Math approach or a different node.
    # The simplest: use two separate nodes. But actually we can get alpha from
    # the color socket by separating in a different way.
    # Let's use ShaderNodeSeparateXYZ for the color (R=X, G=Y, B=Z) and a
    # ShaderNodeMath to extract alpha... No, that's complex.
    #
    # Simplest approach: Blender's Separate Color node has 3 outputs (R, G, B).
    # For alpha, we use a Separate RGBA approach by converting through
    # ShaderNodeMixRGB or by using the alpha output of the original socket.
    #
    # Actually in Blender 4.x, we can use the fact that a Color socket carries RGBA.
    # But Separate Color only exposes R, G, B. For alpha we need:
    nodes.remove(separate_alpha)  # Remove the duplicate

    # For alpha channel as a potential routing source, we'll extract it via a
    # transparent shader trick... or more simply, just compute it with math.
    # The cleanest way: use ShaderNodeSeparateColor for RGB, and for alpha
    # use a dedicated alpha extraction.
    #
    # Blender has no built-in "separate alpha from color" node in the shader editor.
    # BUT: we can use the Alpha output from an Image Texture node upstream.
    # Since we're working generically, let's handle this by checking if any
    # routing actually uses alpha. If not, skip the alpha extraction entirely.

    needs_alpha_input = any(
        shiny_filter.channel_routing[i] == ShinyChannel.ALPHA
        for i in range(3)  # Only check RGB outputs
    )

    # Build channel source outputs: map each ShinyChannel to a node output socket
    channel_sources = {
        ShinyChannel.RED: separate.outputs[0],
        ShinyChannel.GREEN: separate.outputs[1],
        ShinyChannel.BLUE: separate.outputs[2],
    }

    if needs_alpha_input:
        # Extract alpha: multiply color by 0 and add alpha via a workaround
        # Actually the simplest way in Blender 4.x shader nodes:
        # Use a MixRGB node set to multiply with factor=0, which gives us
        # access to alpha through the Alpha output of certain nodes.
        #
        # Better approach: use the "Alpha" output from a ShaderNodeAttribute
        # or pass alpha as a separate socket on the group.
        # Cleanest: add a second input socket for alpha.
        group.interface.new_socket('Alpha', in_out='INPUT', socket_type='NodeSocketFloat')
        alpha_input = group_in.outputs[1]
        channel_sources[ShinyChannel.ALPHA] = alpha_input
    else:
        channel_sources[ShinyChannel.ALPHA] = None

    # For each RGB output channel: route source → multiply by brightness
    scaled_channels = []
    for i in range(3):  # R, G, B
        source_channel = shiny_filter.channel_routing[i]
        source_socket = channel_sources[source_channel]
        brightness_multiplier = shiny_filter.brightness[i] + 1.0  # [-1,1] → [0,2]

        if source_socket is not None:
            mult = nodes.new('ShaderNodeMath')
            mult.operation = 'MULTIPLY'
            mult.name = 'Brightness_%s' % ['R', 'G', 'B'][i]
            links.new(source_socket, mult.inputs[0])
            mult.inputs[1].default_value = brightness_multiplier
            scaled_channels.append(mult.outputs[0])
        else:
            # Alpha source needed but not available — output 0
            value = nodes.new('ShaderNodeValue')
            value.outputs[0].default_value = 0.0
            scaled_channels.append(value.outputs[0])

    # Combine back into color (alpha passes through from original)
    combine = nodes.new('ShaderNodeCombineColor')
    combine.mode = 'RGB'
    links.new(scaled_channels[0], combine.inputs[0])  # Red
    links.new(scaled_channels[1], combine.inputs[1])  # Green
    links.new(scaled_channels[2], combine.inputs[2])  # Blue

    links.new(combine.outputs[0], group_out.inputs[0])

    return group


def setup_shiny_property(armature):
    """Initialize the dat_shiny property on the armature.

    The property itself is registered on bpy.types.Object in BlenderPlugin.register().
    This just sets the initial value.

    Args:
        armature: The Blender armature object.
    """
    armature.dat_shiny = False
    armature["dat_has_shiny"] = True


def insert_shiny_filter(material, node_group, armature):
    """Insert the shiny filter node group into a material's node tree.

    Finds the color source feeding into the main shader and interposes a Mix node
    controlled by a driver on armature["Shiny"] to blend between normal and shiny.

    Args:
        material: bpy.types.Material with use_nodes=True.
        node_group: The ShinyFilter node group (from build_shiny_node_group).
        armature: The armature object with the "Shiny" custom property.
    """
    if not material.use_nodes:
        return

    nodes = material.node_tree.nodes
    links = material.node_tree.links

    # Find the target shader input to interpose on
    target_node, target_input, is_emission = _find_color_input(nodes)
    if target_node is None:
        return

    # Get the current source connected to the target input
    source_link = None
    for link in links:
        if link.to_node == target_node and link.to_socket == target_input:
            source_link = link
            break

    if source_link is None:
        # No link — solid color. Create an RGB node from the default value.
        default_color = list(target_input.default_value)
        rgb_node = nodes.new('ShaderNodeRGB')
        rgb_node.outputs[0].default_value[:] = default_color
        source_output = rgb_node.outputs[0]
    else:
        source_output = source_link.from_socket
        links.remove(source_link)

    # Create the shiny filter group node
    group_node = nodes.new('ShaderNodeGroup')
    group_node.node_tree = node_group
    group_node.name = 'ShinyFilter'

    # Connect source color to group input
    links.new(source_output, group_node.inputs[0])

    # If the group has an Alpha input (index 1), we need to provide alpha.
    # Extract alpha from source color using Separate Color if needed.
    if len(group_node.inputs) > 1:
        sep = nodes.new('ShaderNodeSeparateColor')
        sep.mode = 'RGB'
        links.new(source_output, sep.inputs[0])
        # Separate Color in RGB mode doesn't have alpha output.
        # We need to get alpha another way. Use a Separate XYZ won't help.
        # Actually, ShaderNodeSeparateColor outputs R, G, B — no Alpha.
        # For alpha, we'd need to know it from the material context.
        # In practice, most color sources are RGB (textures connect via Color socket).
        # Set alpha input to 1.0 as fallback, since the Alpha would typically
        # come from a separate texture alpha output in the original chain.
        nodes.remove(sep)
        group_node.inputs[1].default_value = 1.0

    # Create MixRGB node to blend between normal and shiny
    # Using ShaderNodeMixRGB (same pattern as materials.py) for reliable socket indices:
    #   inputs[0] = Fac, inputs[1] = Color1, inputs[2] = Color2, outputs[0] = Color
    mix_node = nodes.new('ShaderNodeMixRGB')
    mix_node.blend_type = 'MIX'
    mix_node.name = 'ShinyMix'
    mix_node.inputs[0].default_value = 0.0  # Fac: 0 = normal, 1 = shiny

    # Color1 = normal (source), Color2 = shiny (filtered)
    links.new(source_output, mix_node.inputs[1])
    links.new(group_node.outputs[0], mix_node.inputs[2])

    # Connect mix output to original target
    links.new(mix_node.outputs[0], target_input)

    # Add driver on mix factor from armature["Shiny"]
    _add_shiny_driver(mix_node.inputs[0], armature)


def _find_color_input(nodes):
    """Find the main color input on the output shader.

    Returns (node, input_socket, is_emission) or (None, None, False).
    """
    # Look for Principled BSDF first
    for node in nodes:
        if node.type == 'BSDF_PRINCIPLED':
            return node, node.inputs['Base Color'], False

    # Look for Emission node (unlit materials)
    for node in nodes:
        if node.type == 'EMISSION':
            return node, node.inputs['Color'], True

    return None, None, False


def _add_shiny_driver(factor_input, armature):
    """Add a driver to a mix node's Factor input driven by armature.dat_shiny.

    Uses the registered bpy.props property (dat_shiny) rather than a raw custom
    property, so that the update callback in BlenderPlugin triggers viewport refresh.
    """
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
