"""Auto-layout for Blender node trees (shader or geometry).

Topological sort from the output node back through inputs; assigns each
node to a column based on its maximum distance from the output and places
them left-to-right. Disconnected nodes pile up in an extra column on the
far left.
"""

NODE_WIDTH = 300
NODE_HEIGHT = 200


def auto_layout(nodes, links, output_type='OUTPUT_MATERIAL'):
    """Arrange nodes left-to-right via topological sort from the output node.

    Args:
        nodes: iterable of nodes (from node_tree.nodes).
        links: iterable of links (from node_tree.links).
        output_type: `bl_idname`/`type` of the output node to start from.
            Common values: `OUTPUT_MATERIAL`, `GROUP_OUTPUT`.
    """
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
        inputs_of.setdefault(target, [])
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


def auto_layout_node_group(nodes, links):
    """Layout a node group (uses GROUP_OUTPUT as the anchor)."""
    auto_layout(nodes, links, output_type='GROUP_OUTPUT')
