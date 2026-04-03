"""Standalone Blender script: Add ambient lighting nodes to all materials on the selected armature.

Run this from Blender's Scripting panel with an armature selected. It adds a
dat_ambient_emission node (Emission shader at low strength) to each material,
approximating HSD's per-material ambient color contribution.

The exporter reads the ambient color from this node when exporting to .dat.

Requires the DAT plugin addon to be enabled.
"""
import bpy

# Default ambient: mid-gray at low strength
DEFAULT_AMBIENT_COLOR = (0.5, 0.5, 0.5, 1.0)  # Linear RGBA
DEFAULT_AMBIENT_STRENGTH = 0.1


def main():
    armature = bpy.context.active_object

    if armature is None or armature.type != 'ARMATURE':
        raise ValueError("Select an armature object before running this script.")

    count = 0
    skipped = 0

    for child in armature.children:
        if child.type != 'MESH':
            continue
        for slot in child.material_slots:
            mat = slot.material
            if not mat or not mat.use_nodes:
                continue

            nodes = mat.node_tree.nodes
            links = mat.node_tree.links

            # Skip if already has ambient node
            if any(n.name == 'dat_ambient_emission' for n in nodes):
                skipped += 1
                continue

            # Find the material output node
            output = None
            for node in nodes:
                if node.type == 'OUTPUT_MATERIAL':
                    output = node
                    break
            if output is None:
                continue

            # Find what's currently connected to the output's Surface input
            surface_link = None
            for link in links:
                if link.to_node == output and link.to_socket == output.inputs['Surface']:
                    surface_link = link
                    break

            if surface_link is None:
                continue

            shader_output = surface_link.from_socket
            links.remove(surface_link)

            # Add ambient emission node
            ambient = nodes.new('ShaderNodeEmission')
            ambient.name = 'dat_ambient_emission'
            ambient.inputs['Color'].default_value = DEFAULT_AMBIENT_COLOR
            ambient.inputs['Strength'].default_value = DEFAULT_AMBIENT_STRENGTH

            # Add shader to mix main shader with ambient
            add_shader = nodes.new('ShaderNodeAddShader')
            add_shader.name = 'dat_ambient_add'
            links.new(shader_output, add_shader.inputs[0])
            links.new(ambient.outputs[0], add_shader.inputs[1])
            links.new(add_shader.outputs[0], output.inputs['Surface'])

            count += 1

    print("Added ambient lighting to %d material(s) on '%s' (%d already had it)." %
          (count, armature.name, skipped))
    print("Adjust the Emission color and strength in each material's node tree to fine-tune.")


main()
