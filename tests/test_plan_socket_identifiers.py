"""The importer plan keys BR shader sockets by Blender socket identifier.

BR references every shader-node socket by its Blender *identifier* — the
single, collision-free convention (a Math node's three inputs are
'Value' / 'Value_001' / 'Value_002', unique unlike their shared display
name). The plan's `BRGraphBuilder` lets call sites wire sockets by
convenient integer index and rewrites each to its identifier at storage
time. These tests pin that rewrite and the completeness of the lookup
table.
"""
import re

import pytest

import importer.phases.plan.helpers.materials as plan_mat
from importer.phases.plan.helpers.materials import (
    BRGraphBuilder, _SOCKET_IDS, _socket_identifier,
)


def test_builder_rewrites_integer_keys_to_identifiers():
    g = BRGraphBuilder()
    math = g.add_node('ShaderNodeMath', input_defaults={1: 0.5})   # input 1 → 'Value_001'
    mix = g.add_node('ShaderNodeMixRGB', input_defaults={0: 0.7})  # input 0 → 'Fac'
    g.add_link(math, 0, mix, 2)  # math output 0 → 'Value'; mix input 2 → 'Color2'
    graph = g.finalize()

    math_node = next(n for n in graph.nodes if n.name == math)
    mix_node = next(n for n in graph.nodes if n.name == mix)
    assert math_node.input_defaults == {'Value_001': 0.5}
    assert mix_node.input_defaults == {'Fac': 0.7}

    link = graph.links[0]
    assert link.from_output == 'Value'
    assert link.to_input == 'Color2'


def test_duplicate_named_inputs_get_distinct_identifiers():
    """A VectorMath's two 'Vector' inputs must not collide — index 0 →
    'Vector', index 1 → 'Vector_001'."""
    g = BRGraphBuilder()
    vm = g.add_node('ShaderNodeVectorMath', input_defaults={1: (2.0, 2.0, 1.0)})
    node = next(n for n in g.finalize().nodes if n.name == vm)
    assert node.input_defaults == {'Vector_001': (2.0, 2.0, 1.0)}


def test_string_keys_pass_through_unchanged():
    g = BRGraphBuilder()
    shader = g.add_node('ShaderNodeBsdfPrincipled')
    rgb = g.add_node('ShaderNodeRGB')
    g.add_link(rgb, 0, shader, 'Base Color')  # name already an identifier
    link = g.finalize().links[0]
    assert link.to_input == 'Base Color'
    assert link.from_output == 'Color'  # rgb output 0 → 'Color'


def test_socket_table_covers_every_builder_node_type():
    """Every node type the plan constructs must have a _SOCKET_IDS entry,
    or its integer socket keys leak past the builder unconverted (this
    test would have caught ShaderNodeVectorMath being absent)."""
    src = open(plan_mat.__file__).read()
    used = set(re.findall(r"add_node\(\s*'([A-Za-z]+)'", src))
    missing = used - set(_SOCKET_IDS)
    assert not missing, "node types missing from _SOCKET_IDS: %s" % sorted(missing)


def test_missing_table_entry_raises_not_passes_through():
    """A tracked node type with no table entry must fail loud, so gaps
    surface at plan time rather than as an unresolvable link at build."""
    with pytest.raises(ValueError):
        _socket_identifier('ShaderNodeNonexistent', 0)
    # An out-of-range index on a known node also raises.
    with pytest.raises(ValueError):
        _socket_identifier('ShaderNodeMixRGB', 9)


def test_untracked_node_passes_key_through():
    """An external/unknown node (None type — e.g. a unit-test fake ref)
    leaves the key untouched; only builder-tracked nodes are rewritten."""
    assert _socket_identifier(None, 3) == 3
