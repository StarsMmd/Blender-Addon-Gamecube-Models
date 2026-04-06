"""Standalone Blender script: Add shiny filter to the selected armature.

Run this from Blender's Scripting panel (Text Editor > Run Script) with an
armature selected. It creates ShinyRoute and ShinyBright node groups with
no-op (identity) parameters and inserts them into every material on the
armature's child meshes.

The routing stage is placed BEFORE any vertex color multiply node, and the
brightness stage is placed AFTER it. This ensures channel routing only
affects texture/material colors, not vertex colors.

The Shiny Variant panel in Object Properties will appear on the armature,
allowing live editing of all 8 shiny parameters (4 channel routing + 4 brightness).

Requires the DAT plugin addon to be enabled (for the registered shiny properties).

Supported material setups:
  - Principled BSDF or Emission shader
  - Vertex colors applied via MixRGB Multiply with ShaderNodeAttribute input
"""
import bpy
import sys
import os

# Add the addon directory to path so we can import from the plugin
addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

from importer.phases.post_process.shiny_filter import (
    build_shiny_route_node_group, build_shiny_bright_node_group,
    setup_shiny_properties, insert_shiny_filter,
)
from shared.IR.shiny import IRShinyFilter
from shared.IR.enums import ShinyChannel


def main():
    armature = bpy.context.active_object

    if armature is None or armature.type != 'ARMATURE':
        raise ValueError("Select an armature object before running this script.")

    if armature.get("dat_pkx_has_shiny"):
        raise ValueError("This armature already has a shiny filter. "
                         "Edit the parameters in the Shiny Variant panel instead.")

    if not hasattr(armature, 'dat_pkx_shiny'):
        raise ValueError("The DAT plugin addon must be enabled for shiny properties to work. "
                         "Enable it in Edit > Preferences > Extensions.")

    model_name = armature.name

    # No-op parameters: identity routing, zero brightness
    ir_filter = IRShinyFilter(
        channel_routing=(ShinyChannel.RED, ShinyChannel.GREEN, ShinyChannel.BLUE, ShinyChannel.ALPHA),
        brightness=(0.0, 0.0, 0.0, 0.0),
    )

    route_name = "ShinyRoute_%s" % model_name
    bright_name = "ShinyBright_%s" % model_name
    route_group = build_shiny_route_node_group(ir_filter, route_name)
    bright_group = build_shiny_bright_node_group(ir_filter, bright_name)
    setup_shiny_properties(armature, ir_filter, route_name, bright_name)

    count = 0
    for child in armature.children:
        if child.type != 'MESH':
            continue
        for slot in child.material_slots:
            if slot.material:
                insert_shiny_filter(slot.material, route_group, bright_group, armature)
                count += 1

    print("Added shiny filter to %d material(s) on '%s'." % (count, model_name))
    print("Use the Shiny Variant panel in Object Properties to adjust parameters.")


main()
