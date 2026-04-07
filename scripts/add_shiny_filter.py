"""Standalone Blender script: Add shiny filter to the selected armature.

Run this from Blender's Scripting panel (Text Editor > Run Script) with an
armature selected. It creates ShinyRoute and ShinyBright node groups with
identity/neutral parameters and inserts them into every material on the
armature's child meshes.

Edit dat_pkx_shiny_route and dat_pkx_shiny_brightness in the Custom Properties
panel to change the shiny appearance. Toggle dat_pkx_shiny in the PKX Metadata
panel to preview the effect.

Requires the DAT plugin addon to be enabled.
"""
import bpy
import sys
import os

addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

from importer.phases.post_process.shiny_filter import (
    build_shiny_route_node_group, build_shiny_bright_node_group,
    setup_shiny_properties, insert_shiny_filter,
)


def main():
    armature = bpy.context.active_object

    if armature is None or armature.type != 'ARMATURE':
        raise ValueError("Select an armature object before running this script.")

    if armature.get("dat_pkx_has_shiny"):
        raise ValueError("This armature already has a shiny filter. "
                         "Edit dat_pkx_shiny_route and dat_pkx_shiny_brightness "
                         "in Custom Properties instead.")

    if not hasattr(armature, 'dat_pkx_shiny'):
        raise ValueError("The DAT plugin addon must be enabled for shiny properties to work. "
                         "Enable it in Edit > Preferences > Extensions.")

    model_name = armature.name

    # Identity routing, neutral brightness
    route = [0, 1, 2, 3]
    brightness = [0.0, 0.0, 0.0]

    # Store as PKX custom properties
    armature["dat_pkx_shiny_route"] = route
    armature["dat_pkx_shiny_brightness"] = brightness

    route_name = "ShinyRoute_%s" % model_name
    bright_name = "ShinyBright_%s" % model_name
    route_group = build_shiny_route_node_group(route, route_name)
    bright_group = build_shiny_bright_node_group(brightness, bright_name)
    setup_shiny_properties(armature, route, brightness, route_name, bright_name)

    count = 0
    for child in armature.children:
        if child.type != 'MESH':
            continue
        for slot in child.material_slots:
            if slot.material:
                insert_shiny_filter(slot.material, route_group, bright_group, armature)
                count += 1

    print("Added shiny filter to %d material(s) on '%s'." % (count, model_name))
    print("Edit dat_pkx_shiny_route / dat_pkx_shiny_brightness in Custom Properties.")
    print("Toggle dat_pkx_shiny in the PKX Metadata panel to preview.")


main()
