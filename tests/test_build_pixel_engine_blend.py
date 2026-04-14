"""Regression: when ir_mat.is_translucent and fragment_blending is None,
the importer must set blend_method='HASHED', not 'BLEND'.

Background: EEVEE's BLEND mode introduces depth-sort artefacts that look
like back-faces showing through (the Greninja tongue/scarf "weird culling"
reported on 2026-04-13 round-trip). Every other transparent branch in
_build_pixel_engine maps to HASHED — only the fb=None fallback was wrong.
"""
from unittest.mock import MagicMock

from importer.phases.build_blender.helpers.materials import _build_pixel_engine


def _make_ir_mat(is_translucent, fragment_blending=None):
    """Minimal stub IRMaterial for the pixel-engine call."""
    ir_mat = MagicMock()
    ir_mat.is_translucent = is_translucent
    ir_mat.fragment_blending = fragment_blending
    return ir_mat


def test_translucent_with_no_fragment_blending_uses_hashed():
    ir_mat = _make_ir_mat(is_translucent=True, fragment_blending=None)
    mat = MagicMock()
    mat.blend_method = 'OPAQUE'

    _, _, transparent_shader, alt = _build_pixel_engine(
        ir_mat, nodes=MagicMock(), links=MagicMock(),
        last_color=MagicMock(), last_alpha=MagicMock(), mat=mat,
    )

    assert mat.blend_method == 'HASHED', (
        "Translucent material with no explicit fragment_blending must "
        "use HASHED to avoid EEVEE depth-sort artefacts"
    )
    assert transparent_shader is True
    assert alt == 'NOTHING'


def test_opaque_with_no_fragment_blending_leaves_blend_method_alone():
    ir_mat = _make_ir_mat(is_translucent=False, fragment_blending=None)
    mat = MagicMock()
    mat.blend_method = 'OPAQUE'

    _, _, transparent_shader, alt = _build_pixel_engine(
        ir_mat, nodes=MagicMock(), links=MagicMock(),
        last_color=MagicMock(), last_alpha=MagicMock(), mat=mat,
    )

    assert mat.blend_method == 'OPAQUE', (
        "Opaque material with no fragment_blending must not be touched"
    )
    assert transparent_shader is False
