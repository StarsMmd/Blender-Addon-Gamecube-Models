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
"""
import bpy
import sys
import os

addon_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if addon_dir not in sys.path:
    sys.path.insert(0, addon_dir)

from importer.phases.post_process.shiny_filter import (
    build_shiny_route_node_group, build_shiny_bright_node_group,
    insert_shiny_filter, SHINY_ROUTE_GROUP, SHINY_BRIGHT_GROUP,
)


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

    route_group = build_shiny_route_node_group(route, SHINY_ROUTE_GROUP)
    bright_group = build_shiny_bright_node_group(brightness, SHINY_BRIGHT_GROUP)

    count = 0
    for child in armature.children:
        if child.type != 'MESH':
            continue
        for slot in child.material_slots:
            if slot.material:
                insert_shiny_filter(slot.material, route_group, bright_group, armature)
                count += 1

    print("Added shiny filter to %d material(s) on '%s'." % (count, armature.name))
    print("Edit dat_pkx_shiny_route / dat_pkx_shiny_brightness in Custom Properties.")
    print("Toggle dat_pkx_shiny in the PKX Metadata panel to preview.")


main()
