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

Tests construct BR-side fixtures (no bpy required) and run them
through the plan-side decoder so the assertion exercises the BR ↔ IR
translation path the production exporter uses.
"""
from shared.BR.materials import BRMaterial, BRNodeGraph, BRNode, BRLink
from shared.IR.enums import LightingModel
from exporter.phases.plan.helpers.materials import plan_material


def _br_mat(*, has_principled, base_color_linked, base_color_value,
            has_emission):
    """Build the smallest BRMaterial that triggers the lighting branch."""
    nodes = []
    links = []
    if has_principled:
        input_defaults = {
            'Specular IOR Level': 0.5,
            'Specular Tint': (0.0, 0.0, 0.0, 1.0),
            'Alpha': 1.0,
        }
        if not base_color_linked:
            input_defaults['Base Color'] = tuple(base_color_value)
        nodes.append(BRNode(
            node_type='ShaderNodeBsdfPrincipled',
            name='Principled BSDF',
            input_defaults=input_defaults,
        ))
        if base_color_linked:
            # A live Base Color routes through some upstream node — for
            # the lighting test the source's identity doesn't matter, we
            # only need the link to exist.
            nodes.append(BRNode(node_type='ShaderNodeRGB', name='Color',
                                properties={'color': tuple(base_color_value)}))
            links.append(BRLink(from_node='Color', from_output='Color',
                                to_node='Principled BSDF', to_input='Base Color'))
    if has_emission:
        nodes.append(BRNode(node_type='ShaderNodeEmission', name='Emission'))
    nodes.append(BRNode(node_type='ShaderNodeOutputMaterial',
                        name='Material Output'))
    return BRMaterial(name='test_mat', node_graph=BRNodeGraph(nodes=nodes, links=links))


def test_unlit_pattern_principled_plus_emission_black_base():
    """Importer's UNLIT build: Principled with Base Color=(0,0,0) +
    Emission combined via AddShader. Must classify UNLIT."""
    mat = _br_mat(
        has_principled=True, base_color_linked=False,
        base_color_value=[0.0, 0.0, 0.0, 1.0], has_emission=True,
    )
    assert plan_material(mat).lighting == LightingModel.UNLIT


def test_lit_pattern_principled_with_linked_base_color():
    """LIT: Base Color wired to a texture/shader chain."""
    mat = _br_mat(
        has_principled=True, base_color_linked=True,
        base_color_value=[1.0, 1.0, 1.0, 1.0], has_emission=False,
    )
    assert plan_material(mat).lighting == LightingModel.LIT


def test_lit_with_ambient_emission_still_lit():
    """LIT materials can carry a secondary Emission node for ambient
    approximation; Base Color still routes through Principled so the
    material is LIT — NOT UNLIT."""
    mat = _br_mat(
        has_principled=True, base_color_linked=True,
        base_color_value=[1.0, 1.0, 1.0, 1.0], has_emission=True,
    )
    assert plan_material(mat).lighting == LightingModel.LIT


def test_emission_only_classifies_unlit():
    """Pure-emission material (no Principled) → UNLIT."""
    mat = _br_mat(
        has_principled=False, base_color_linked=False,
        base_color_value=[0, 0, 0, 1], has_emission=True,
    )
    assert plan_material(mat).lighting == LightingModel.UNLIT


def test_principled_only_classifies_lit():
    """No Emission → LIT regardless of Base Color value."""
    mat = _br_mat(
        has_principled=True, base_color_linked=False,
        base_color_value=[0.0, 0.0, 0.0, 1.0], has_emission=False,
    )
    assert plan_material(mat).lighting == LightingModel.LIT
