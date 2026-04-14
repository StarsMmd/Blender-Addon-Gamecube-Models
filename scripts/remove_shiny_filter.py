"""Standalone Blender script: Remove all DAT shiny filter nodes.

Run this from Blender's Scripting panel (Text Editor > Run Script). It strips
the shiny route/brightness nodes from every material in the file and removes
the shared DATPlugin_ShinyRoute / DATPlugin_ShinyBright node groups so the
filter can be reapplied from scratch (e.g. after updating the shiny script).

Per-material nodes removed (by name):
  shiny_route_shader, shiny_route_mix, shiny_bright_shader, shiny_bright_mix

The "normal path" link feeding each mix node's input[1] is reconnected to
whatever the mix node was driving, so the underlying material wiring is
restored. Drivers on the mix Factor inputs are removed first so Blender
doesn't keep stale dependencies after the nodes are deleted.

Custom properties (dat_pkx_shiny, dat_pkx_shiny_route_*, dat_pkx_shiny_brightness_*)
on the armature are left untouched — reapply the filter to use them again.

This script is fully standalone — no imports from the plugin codebase.
"""
import bpy

SHINY_GROUP_NAMES = ("DATPlugin_ShinyRoute", "DATPlugin_ShinyBright")
MIX_NODE_NAMES = ("shiny_route_mix", "shiny_bright_mix")
GROUP_NODE_NAMES = ("shiny_route_shader", "shiny_bright_shader")


def _remove_factor_driver(mix_node):
    try:
        mix_node.inputs[0].driver_remove("default_value")
    except (RuntimeError, TypeError):
        pass


def _bypass_mix(node_tree, mix_node):
    """Reconnect the mix node's normal-path input to its downstream consumers."""
    links = node_tree.links

    upstream_socket = None
    for link in list(links):
        if link.to_node == mix_node and link.to_socket == mix_node.inputs[1]:
            upstream_socket = link.from_socket
            links.remove(link)
            break

    downstream = []
    for link in list(links):
        if link.from_node == mix_node:
            downstream.append((link.to_node, link.to_socket))
            links.remove(link)

    if upstream_socket is not None:
        for to_node, to_socket in downstream:
            links.new(upstream_socket, to_socket)


def _strip_material(material):
    if not material.use_nodes or material.node_tree is None:
        return 0

    nodes = material.node_tree.nodes
    removed = 0

    for mix_name in MIX_NODE_NAMES:
        mix_node = nodes.get(mix_name)
        if mix_node is None:
            continue
        _remove_factor_driver(mix_node)
        _bypass_mix(material.node_tree, mix_node)
        nodes.remove(mix_node)
        removed += 1

    for group_name in GROUP_NODE_NAMES:
        group_node = nodes.get(group_name)
        if group_node is None:
            continue
        nodes.remove(group_node)
        removed += 1

    return removed


def main():
    material_count = 0
    node_count = 0
    for material in bpy.data.materials:
        removed = _strip_material(material)
        if removed:
            material_count += 1
            node_count += removed

    group_count = 0
    for group_name in SHINY_GROUP_NAMES:
        group = bpy.data.node_groups.get(group_name)
        if group is not None:
            bpy.data.node_groups.remove(group)
            group_count += 1

    print("[remove_shiny_filter] Removed %d nodes from %d materials, %d node groups."
          % (node_count, material_count, group_count))


main()
