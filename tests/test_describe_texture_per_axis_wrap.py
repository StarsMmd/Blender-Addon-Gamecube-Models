"""Regression: per-axis wrap mode (wrap_s ≠ wrap_t, and MIRROR) must
round-trip faithfully through describe_blender.

Blender's `ShaderNodeTexImage.extension` is a single-value enum covering
both axes, so the importer builds a per-axis UV math chain
(`Separate → per-axis Math op → Combine`) whenever the wrap modes
disagree or either axis is MIRROR. `_detect_per_axis_wrap` on the
export side pattern-matches that chain to recover wrap_s and wrap_t
independently.

Op encoding:
  - REPEAT → ShaderNodeMath(FRACT)
  - CLAMP  → ShaderNodeMath(MAXIMUM 0.0) → ShaderNodeMath(MINIMUM 1.0)
  - MIRROR → ShaderNodeMath(PINGPONG, 1.0)

Before this fix, the exporter always collapsed `wrap_t = wrap_s` from
the single `tex_node.extension`, which lost MIRROR entirely and
silently flipped asymmetric CLAMP/REPEAT combinations.
"""
from unittest.mock import MagicMock

from exporter.phases.describe.helpers.materials_decode import (
    _detect_per_axis_wrap,
)
from shared.IR.enums import WrapMode


# --- helpers to build stub Blender-like nodes --------------------------------

def _math(op, upstream_output=None):
    n = MagicMock()
    n.bl_idname = 'ShaderNodeMath'
    n.operation = op
    inp = MagicMock()
    inp.is_linked = upstream_output is not None
    if upstream_output is not None:
        link = MagicMock(); link.from_node = upstream_output
        inp.links = [link]
    else:
        inp.links = []
    n.inputs = [inp]
    return n


def _output_of(node):
    """Return a 'node' object that, when referenced as from_node on a
    link, represents the upstream node producing the wire."""
    return node


def _axis_socket(feeding_node):
    s = MagicMock()
    s.is_linked = feeding_node is not None
    if feeding_node is not None:
        link = MagicMock(); link.from_node = feeding_node
        s.links = [link]
    return s


def _combine(s_feed, t_feed):
    n = MagicMock()
    n.bl_idname = 'ShaderNodeCombineXYZ'
    n.inputs = [_axis_socket(s_feed), _axis_socket(t_feed), _axis_socket(None)]
    return n


def _tex_node(vec_source):
    tex = MagicMock()
    vec = MagicMock()
    vec.name = 'Vector'
    vec.is_linked = vec_source is not None
    if vec_source is not None:
        link = MagicMock(); link.from_node = vec_source
        vec.links = [link]
    tex.inputs = [vec]
    return tex


# --- Per-axis detection cases -----------------------------------------------

def test_repeat_fract_on_s_axis():
    chain = _combine(_math('FRACT'), _math('FRACT'))
    ws, wt = _detect_per_axis_wrap(_tex_node(chain), links=None)
    assert ws == WrapMode.REPEAT
    assert wt == WrapMode.REPEAT


def test_mirror_pingpong_on_both_axes():
    chain = _combine(_math('PINGPONG'), _math('PINGPONG'))
    ws, wt = _detect_per_axis_wrap(_tex_node(chain), links=None)
    assert ws == WrapMode.MIRROR
    assert wt == WrapMode.MIRROR


def test_asymmetric_repeat_clamp():
    # S = REPEAT (FRACT); T = CLAMP (MAXIMUM→MINIMUM)
    max0 = _math('MAXIMUM')
    min1 = _math('MINIMUM', upstream_output=max0)
    chain = _combine(_math('FRACT'), min1)
    ws, wt = _detect_per_axis_wrap(_tex_node(chain), links=None)
    assert ws == WrapMode.REPEAT
    assert wt == WrapMode.CLAMP


def test_asymmetric_mirror_clamp():
    # Absol's 128×128 MIRROR/CLAMP case
    max0 = _math('MAXIMUM')
    min1 = _math('MINIMUM', upstream_output=max0)
    chain = _combine(_math('PINGPONG'), min1)
    ws, wt = _detect_per_axis_wrap(_tex_node(chain), links=None)
    assert ws == WrapMode.MIRROR
    assert wt == WrapMode.CLAMP


def test_asymmetric_clamp_repeat():
    max0 = _math('MAXIMUM')
    min1 = _math('MINIMUM', upstream_output=max0)
    chain = _combine(min1, _math('FRACT'))
    ws, wt = _detect_per_axis_wrap(_tex_node(chain), links=None)
    assert ws == WrapMode.CLAMP
    assert wt == WrapMode.REPEAT


def test_no_uv_math_chain_returns_none():
    """No Combine node → no per-axis chain → caller should fall back
    to tex_node.extension."""
    tex = _tex_node(None)  # vector input unlinked
    ws, wt = _detect_per_axis_wrap(tex, links=None)
    assert ws is None
    assert wt is None


def test_non_combine_source_returns_none():
    """Vector wired but not from Combine → not our chain → fall back."""
    mapping = MagicMock(); mapping.bl_idname = 'ShaderNodeMapping'
    ws, wt = _detect_per_axis_wrap(_tex_node(mapping), links=None)
    assert ws is None
    assert wt is None


def test_partial_clamp_chain_not_matched():
    """MINIMUM without an upstream MAXIMUM isn't our CLAMP pattern —
    returns None for that axis so caller uses the fallback."""
    # Bare MINIMUM with no upstream link
    chain = _combine(_math('MINIMUM'), _math('FRACT'))
    ws, wt = _detect_per_axis_wrap(_tex_node(chain), links=None)
    assert ws is None  # partial match → None
    assert wt == WrapMode.REPEAT
