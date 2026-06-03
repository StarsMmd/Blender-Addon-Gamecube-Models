"""Regression: translucent materials with no fragment_blending must map to
blend_method='HASHED', not 'BLEND'.

Background: EEVEE's BLEND mode introduces depth-sort artefacts that look
like back-faces showing through a translucent material. Every other
transparent branch in the pixel-engine planner routes to HASHED — only
the ``fragment_blending=None`` fallback used to route to BLEND. The
Plan-phase migration keeps the same mapping; this test exercises it.
"""
from unittest.mock import MagicMock

from importer.phases.plan.helpers.materials import _plan_pixel_engine, BRGraphBuilder


def _make_ir_mat(is_translucent, fragment_blending=None):
    ir_mat = MagicMock()
    ir_mat.is_translucent = is_translucent
    ir_mat.fragment_blending = fragment_blending
    return ir_mat


def test_translucent_with_no_fragment_blending_uses_hashed():
    ir_mat = _make_ir_mat(is_translucent=True, fragment_blending=None)
    g = BRGraphBuilder()

    _, _, transparent, alt, blend_method = _plan_pixel_engine(
        g, ir_mat, ('c', 0), ('a', 0),
    )

    assert blend_method == 'HASHED', (
        "Translucent material with no fragment_blending must map to HASHED"
    )
    assert transparent is True
    assert alt == 'NOTHING'


def test_opaque_with_no_fragment_blending_leaves_blend_method_alone():
    ir_mat = _make_ir_mat(is_translucent=False, fragment_blending=None)
    g = BRGraphBuilder()

    _, _, transparent, alt, blend_method = _plan_pixel_engine(
        g, ir_mat, ('c', 0), ('a', 0),
    )

    assert blend_method is None, "Opaque materials should leave blend_method as default"
    assert transparent is False
    assert alt == 'NOTHING'
