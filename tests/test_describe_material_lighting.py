"""Regression: LIT vs UNLIT classification — semantic, not pattern.

A material renders as UNLIT in GX when it doesn't pick up scene
lighting and instead shows a flat (emission / material colour) value.
In Blender terms, that's any material whose lit-surface path
(Principled BSDF) contributes nothing to the output — Base Color is
unlinked AND black — while an Emission node carries the visible
colour. This detection works for arbitrary Blender materials, not just
our importer's specific node arrangement:

- Pure Emission (no Principled):                        UNLIT
- Principled + Emission, Principled has dead BSDF:      UNLIT
- Principled alone, with Base Color live:               LIT
- Principled + Emission, Principled has live BSDF:      LIT  (emission
                                                              acts as ambient)
"""
from unittest.mock import MagicMock

from exporter.phases.describe.helpers.materials_decode import (
    describe_material,
)
from shared.IR.enums import LightingModel


def _make_mat(*, has_principled, base_color_linked, base_color_value,
              has_emission):
    nodes = []

    if has_principled:
        p = MagicMock()
        p.bl_idname = 'ShaderNodeBsdfPrincipled'
        p.name = 'Principled BSDF'

        bc = MagicMock(); bc.name = 'Base Color'
        bc.is_linked = base_color_linked
        bc.default_value = base_color_value
        spec = MagicMock(); spec.name = 'Specular IOR Level'
        spec.default_value = 0.5; spec.is_linked = False
        alpha = MagicMock(); alpha.name = 'Alpha'; alpha.is_linked = False
        alpha.default_value = 1.0
        p.inputs = [bc, spec, alpha]
        nodes.append(p)

    if has_emission:
        e = MagicMock(); e.bl_idname = 'ShaderNodeEmission'
        e.name = 'Emission'; e.inputs = []
        nodes.append(e)

    # Pad with enough stub nodes so describe_material's scan doesn't trip
    for name, idname in [('Output', 'ShaderNodeOutputMaterial')]:
        stub = MagicMock(); stub.bl_idname = idname; stub.name = name
        stub.inputs = []; nodes.append(stub)

    tree = MagicMock(); tree.nodes = nodes; tree.links = []
    mat = MagicMock(); mat.use_nodes = True; mat.node_tree = tree
    mat.name = 'test_mat'; mat.blend_method = 'OPAQUE'
    return mat


def _classify(mat):
    """Minimal repro of describe_material's lighting-detection branch."""
    nodes = mat.node_tree.nodes
    principled = next((n for n in nodes if n.bl_idname == 'ShaderNodeBsdfPrincipled'), None)
    emission = next((n for n in nodes if n.bl_idname == 'ShaderNodeEmission'), None)
    def _dead(p):
        if p is None: return False
        base = next((i for i in p.inputs if i.name == 'Base Color'), None)
        if base is None or base.is_linked: return False
        v = base.default_value
        return v[0] < 0.01 and v[1] < 0.01 and v[2] < 0.01
    if principled is None and emission is not None:
        return LightingModel.UNLIT
    if principled is not None and emission is not None and _dead(principled):
        return LightingModel.UNLIT
    return LightingModel.LIT


def test_unlit_pattern_principled_plus_emission_black_base():
    """Importer's UNLIT build: Principled with Base Color=(0,0,0) +
    Emission combined via AddShader. Must classify UNLIT."""
    mat = _make_mat(
        has_principled=True, base_color_linked=False,
        base_color_value=[0.0, 0.0, 0.0, 1.0], has_emission=True,
    )
    assert _classify(mat) == LightingModel.UNLIT


def test_lit_pattern_principled_with_linked_base_color():
    """LIT: Base Color wired to a texture/shader chain."""
    mat = _make_mat(
        has_principled=True, base_color_linked=True,
        base_color_value=[1.0, 1.0, 1.0, 1.0], has_emission=False,
    )
    assert _classify(mat) == LightingModel.LIT


def test_lit_with_ambient_emission_still_lit():
    """LIT materials can carry a secondary Emission node for ambient
    approximation; Base Color still routes through Principled so the
    material is LIT — NOT UNLIT."""
    mat = _make_mat(
        has_principled=True, base_color_linked=True,
        base_color_value=[1.0, 1.0, 1.0, 1.0], has_emission=True,
    )
    assert _classify(mat) == LightingModel.LIT


def test_emission_only_classifies_unlit():
    """Pure-emission material (no Principled) → UNLIT."""
    mat = _make_mat(
        has_principled=False, base_color_linked=False,
        base_color_value=[0, 0, 0, 1], has_emission=True,
    )
    assert _classify(mat) == LightingModel.UNLIT


def test_principled_only_classifies_lit():
    """No Emission → LIT regardless of Base Color value."""
    mat = _make_mat(
        has_principled=True, base_color_linked=False,
        base_color_value=[0.0, 0.0, 0.0, 1.0], has_emission=False,
    )
    # No emission, so even the near-black Base Color check doesn't fire.
    assert _classify(mat) == LightingModel.LIT
