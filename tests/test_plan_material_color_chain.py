"""Regression: only ShaderNodeTexImage nodes that feed a colour input
should become TObj layers on export.

PBR-style materials authored outside this importer (GLB/FBX rips,
Sketchfab models, etc.) typically wire 5-7 ShaderNodeTexImage nodes
into a Principled BSDF — Base Color, Normal, Roughness, Metallic, AO,
Emissive. Earlier versions of the exporter emitted every TexImage as
its own TObj on its own TEV stage, which on Colo/XD produces wildly
broken output (the GX vertex carries one UV channel, so the auxiliary
stages sample undefined coords and the TEV combiner collapses the
fragment to black or white).

The plan-side filter in `_extract_texture_layers` keeps only TexImage
nodes whose Color output reaches a colour-consuming socket through
colour-preserving nodes. Aux maps (Normal/Roughness/Metallic/etc.) hit
inputs that aren't colour sinks, so they are correctly dropped.
"""
from shared.BR.materials import (
    BRImage, BRMaterial, BRNode, BRNodeGraph, BRLink,
)
from exporter.phases.plan.helpers.materials import plan_material


def _img(name):
    return BRImage(name=name, width=4, height=4,
                   pixels=b'\x00' * 64, cache_key=(name, None))


def _tex(name, image_name):
    return BRNode(node_type='ShaderNodeTexImage', name=name,
                  image_ref=_img(image_name))


def _bsdf(name='bsdf', base_color=(0.0, 0.0, 0.0, 1.0)):
    return BRNode(node_type='ShaderNodeBsdfPrincipled', name=name,
                  input_defaults={'Base Color': base_color,
                                  'Specular IOR Level': 0.5})


def _output(name='output'):
    return BRNode(node_type='ShaderNodeOutputMaterial', name=name)


def _link(a, ao, b, bi):
    return BRLink(from_node=a, from_output=ao, to_node=b, to_input=bi)


def _material(nodes, links):
    return BRMaterial(name='m', node_graph=BRNodeGraph(nodes=nodes, links=links))


def test_base_color_texture_produces_one_layer():
    nodes = [_tex('color_tex', 'albedo'), _bsdf(), _output()]
    links = [
        _link('color_tex', 'Color', 'bsdf', 'Base Color'),
        _link('bsdf', 'BSDF', 'output', 'Surface'),
    ]
    ir = plan_material(_material(nodes, links))
    assert len(ir.texture_layers) == 1
    assert ir.texture_layers[0].image.name == 'albedo'


def test_pbr_aux_maps_are_dropped():
    """Normal / Roughness / Metallic / AO / Emissive textures hit BSDF
    inputs that aren't colour sinks → must not become TObj layers."""
    nodes = [
        _tex('color_tex', 'albedo'),
        _tex('normal_tex', 'normal'),
        BRNode(node_type='ShaderNodeNormalMap', name='normal_map'),
        _tex('roughness_tex', 'roughness'),
        _tex('metallic_tex', 'metallic'),
        _tex('emissive_tex', 'emissive'),
        _bsdf(),
        _output(),
    ]
    links = [
        _link('color_tex', 'Color', 'bsdf', 'Base Color'),
        _link('normal_tex', 'Color', 'normal_map', 'Color'),
        _link('normal_map', 'Normal', 'bsdf', 'Normal'),
        _link('roughness_tex', 'Color', 'bsdf', 'Roughness'),
        _link('metallic_tex', 'Color', 'bsdf', 'Metallic'),
        _link('emissive_tex', 'Color', 'bsdf', 'Emission Color'),
        _link('bsdf', 'BSDF', 'output', 'Surface'),
    ]
    ir = plan_material(_material(nodes, links))
    layer_images = [layer.image.name for layer in ir.texture_layers]
    # Albedo (Base Color) and emissive (Emission Color) are colour sinks;
    # normal/roughness/metallic are not.
    assert 'albedo' in layer_images
    assert 'emissive' in layer_images
    assert 'normal' not in layer_images
    assert 'roughness' not in layer_images
    assert 'metallic' not in layer_images
    assert len(ir.texture_layers) == 2


def test_color_texture_through_mixrgb_kept():
    """MixRGB is colour-passthrough — a tex feeding it that ultimately
    reaches Base Color must still be kept."""
    nodes = [
        _tex('layer0', 'imgA'),
        _tex('layer1', 'imgB'),
        BRNode(node_type='ShaderNodeMixRGB', name='mix'),
        _bsdf(), _output(),
    ]
    links = [
        _link('layer0', 'Color', 'mix', 'Color1'),
        _link('layer1', 'Color', 'mix', 'Color2'),
        _link('mix', 'Color', 'bsdf', 'Base Color'),
        _link('bsdf', 'BSDF', 'output', 'Surface'),
    ]
    ir = plan_material(_material(nodes, links))
    assert {layer.image.name for layer in ir.texture_layers} == {'imgA', 'imgB'}


def test_alpha_only_texture_is_dropped():
    """A texture wired only to BSDF.Alpha (and nothing colour-bearing)
    is not a colour layer for GX purposes."""
    nodes = [
        _tex('color_tex', 'albedo'),
        _tex('alpha_tex', 'alpha'),
        _bsdf(), _output(),
    ]
    links = [
        _link('color_tex', 'Color', 'bsdf', 'Base Color'),
        _link('alpha_tex', 'Alpha', 'bsdf', 'Alpha'),
        _link('bsdf', 'BSDF', 'output', 'Surface'),
    ]
    ir = plan_material(_material(nodes, links))
    assert {layer.image.name for layer in ir.texture_layers} == {'albedo'}


def test_texture_feeding_emission_node_kept():
    nodes = [
        _tex('emit_tex', 'emit'),
        BRNode(node_type='ShaderNodeEmission', name='emission'),
        _output(),
    ]
    links = [
        _link('emit_tex', 'Color', 'emission', 'Color'),
        _link('emission', 'Emission', 'output', 'Surface'),
    ]
    ir = plan_material(_material(nodes, links))
    assert len(ir.texture_layers) == 1
    assert ir.texture_layers[0].image.name == 'emit'
