"""Regression: per-axis wrap mode (wrap_s ≠ wrap_t, and MIRROR) must
round-trip faithfully through the exporter.

Blender's `ShaderNodeTexImage.extension` is a single-value enum covering
both axes, so the importer builds a per-axis UV math chain
(`Separate → per-axis Math op → Combine`) whenever the wrap modes
disagree or either axis is MIRROR. The plan-side decoder
(`_detect_per_axis_wrap` in `exporter/phases/plan/helpers/materials.py`)
pattern-matches that chain to recover wrap_s and wrap_t independently
from the BR node graph.

Op encoding:
  - REPEAT → ShaderNodeMath(FRACT)
  - CLAMP  → ShaderNodeMath(MAXIMUM 0.0) → ShaderNodeMath(MINIMUM 1.0)
  - MIRROR → ShaderNodeMath(PINGPONG, 1.0)

Before this regression guard existed the exporter always collapsed
`wrap_t = wrap_s` from the single `tex_node.extension`, which lost
MIRROR entirely and silently flipped asymmetric CLAMP/REPEAT
combinations.
"""
from shared.BR.materials import BRNodeGraph, BRNode, BRLink
from shared.IR.enums import WrapMode
from exporter.phases.plan.helpers.materials import (
    _detect_per_axis_wrap, _GraphView,
)


# --- BR-node fixture builders ----------------------------------------------

class _GraphBuilder:
    """Tiny accumulator that hands out unique BRNode names so chains
    can be wired with `link_into(...)` without manual bookkeeping."""

    def __init__(self):
        self.nodes = []
        self.links = []
        self._counter = 0

    def add(self, node_type, **properties):
        self._counter += 1
        name = "%s_%d" % (node_type, self._counter)
        self.nodes.append(BRNode(node_type=node_type, name=name,
                                 properties=properties))
        return name

    def link(self, from_node, to_node, to_input, from_output='Value'):
        self.links.append(BRLink(from_node=from_node, from_output=from_output,
                                 to_node=to_node, to_input=to_input))

    def view(self):
        return _GraphView(BRNodeGraph(nodes=list(self.nodes),
                                      links=list(self.links)))


def _math(b, op, upstream=None):
    name = b.add('ShaderNodeMath', operation=op)
    if upstream is not None:
        b.link(upstream, name, 'Value')
    return name


def _clamp_chain(b):
    """MAXIMUM(0) → MINIMUM(1) — the importer's CLAMP encoding."""
    mx = _math(b, 'MAXIMUM')
    mn = _math(b, 'MINIMUM', upstream=mx)
    return mn


def _build_with_combine(s_axis, t_axis):
    """Build a graph: ShaderNodeCombineXYZ(X=s_axis, Y=t_axis) →
    ShaderNodeTexImage. Each axis arg is a function that takes the
    builder and returns the upstream node-name feeding that combine
    socket (or None to leave the socket unconnected)."""
    b = _GraphBuilder()
    combine = b.add('ShaderNodeCombineXYZ')
    if s_axis is not None:
        b.link(s_axis(b), combine, 'X')
    if t_axis is not None:
        b.link(t_axis(b), combine, 'Y')
    tex = b.add('ShaderNodeTexImage', extension='REPEAT')
    b.link(combine, tex, 'Vector', from_output='Vector')
    view = b.view()
    return view, view.nodes_by_name[tex]


def _fract(b): return _math(b, 'FRACT')
def _pingpong(b): return _math(b, 'PINGPONG')
def _clamp(b): return _clamp_chain(b)


# --- Per-axis detection cases -----------------------------------------------

def test_repeat_fract_on_both_axes():
    view, tex = _build_with_combine(_fract, _fract)
    ws, wt = _detect_per_axis_wrap(view, tex)
    assert ws == WrapMode.REPEAT
    assert wt == WrapMode.REPEAT


def test_mirror_pingpong_on_both_axes():
    view, tex = _build_with_combine(_pingpong, _pingpong)
    ws, wt = _detect_per_axis_wrap(view, tex)
    assert ws == WrapMode.MIRROR
    assert wt == WrapMode.MIRROR


def test_asymmetric_repeat_clamp():
    view, tex = _build_with_combine(_fract, _clamp)
    ws, wt = _detect_per_axis_wrap(view, tex)
    assert ws == WrapMode.REPEAT
    assert wt == WrapMode.CLAMP


def test_asymmetric_mirror_clamp():
    """Absol's 128×128 MIRROR/CLAMP case."""
    view, tex = _build_with_combine(_pingpong, _clamp)
    ws, wt = _detect_per_axis_wrap(view, tex)
    assert ws == WrapMode.MIRROR
    assert wt == WrapMode.CLAMP


def test_asymmetric_clamp_repeat():
    view, tex = _build_with_combine(_clamp, _fract)
    ws, wt = _detect_per_axis_wrap(view, tex)
    assert ws == WrapMode.CLAMP
    assert wt == WrapMode.REPEAT


def test_no_uv_math_chain_returns_none():
    """Vector input unlinked → no chain to detect → None for both."""
    b = _GraphBuilder()
    tex = b.add('ShaderNodeTexImage', extension='REPEAT')
    view = b.view()
    ws, wt = _detect_per_axis_wrap(view, view.nodes_by_name[tex])
    assert ws is None
    assert wt is None


def test_non_combine_source_returns_none():
    """Vector wired to something other than CombineXYZ → not our chain."""
    b = _GraphBuilder()
    mapping = b.add('ShaderNodeMapping')
    tex = b.add('ShaderNodeTexImage', extension='REPEAT')
    b.link(mapping, tex, 'Vector', from_output='Vector')
    view = b.view()
    ws, wt = _detect_per_axis_wrap(view, view.nodes_by_name[tex])
    assert ws is None
    assert wt is None


def test_partial_clamp_chain_not_matched():
    """A bare MINIMUM with no upstream MAXIMUM isn't the importer's
    CLAMP pattern — that axis returns None so the caller falls back to
    `tex_node.extension`."""
    def _bare_min(b): return _math(b, 'MINIMUM')
    view, tex = _build_with_combine(_bare_min, _fract)
    ws, wt = _detect_per_axis_wrap(view, tex)
    assert ws is None
    assert wt == WrapMode.REPEAT
