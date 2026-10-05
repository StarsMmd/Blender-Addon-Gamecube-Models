"""Tests for the shiny filter's per-material stage selection.

The game appends the brightness modulation TEV stage to every material, but
the colour swap only reaches texture samples and rasterised (vertex) colours.
These tests drive the pure chain-walker and the insertion entry point with
duck-typed fakes — no live Blender scene required.
"""
from unittest.mock import MagicMock

import pytest

from importer.phases.post_process import shiny_filter as sf


# ---------------------------------------------------------------------------
# Minimal duck-typed node-tree fakes
# ---------------------------------------------------------------------------

class _Socket:
    def __init__(self, node, name, default=(0.5, 0.5, 0.5, 1.0)):
        self.node = node
        self.name = name
        self.default_value = list(default)
        self.links = []

    @property
    def is_linked(self):
        return bool(self.links)

    def driver_add(self, _path):
        return MagicMock()


class _SocketList(list):
    def __getitem__(self, key):
        if isinstance(key, str):
            for sock in self:
                if sock.name == key:
                    return sock
            raise KeyError(key)
        return list.__getitem__(self, key)


_SOCKETS = {
    'ShaderNodeBsdfPrincipled': (['Base Color', 'Alpha'], ['BSDF'], 'BSDF_PRINCIPLED'),
    'ShaderNodeTexImage': (['Vector'], ['Color', 'Alpha'], 'TEX_IMAGE'),
    'ShaderNodeAttribute': ([], ['Color', 'Vector', 'Fac', 'Alpha'], 'ATTRIBUTE'),
    'ShaderNodeMixRGB': (['Fac', 'Color1', 'Color2'], ['Color'], 'MIX_RGB'),
    'ShaderNodeRGB': ([], ['Color'], 'RGB'),
    'ShaderNodeGroup': (['Color'], ['Color'], 'GROUP'),
    'ShaderNodeValue': ([], ['Value'], 'VALUE'),
}


class _Node:
    def __init__(self, bl_idname):
        inputs, outputs, ntype = _SOCKETS[bl_idname]
        self.bl_idname = bl_idname
        self.type = ntype
        self.name = bl_idname
        self.inputs = _SocketList(_Socket(self, n) for n in inputs)
        self.outputs = _SocketList(_Socket(self, n) for n in outputs)
        self.node_tree = None
        self.blend_type = None


class _Link:
    def __init__(self, from_socket, to_socket):
        self.from_socket = from_socket
        self.from_node = from_socket.node
        self.to_socket = to_socket
        self.to_node = to_socket.node


class _Nodes(list):
    def new(self, bl_idname):
        node = _Node(bl_idname)
        self.append(node)
        return node


class _Links(list):
    def new(self, from_socket, to_socket):
        link = _Link(from_socket, to_socket)
        from_socket.links.append(link)
        to_socket.links.append(link)
        self.append(link)
        return link

    def remove(self, link):
        link.from_socket.links.remove(link)
        link.to_socket.links.remove(link)
        list.remove(self, link)


class _Material:
    def __init__(self, name='mat'):
        self.name = name
        self.use_nodes = True
        self.node_tree = MagicMock()
        self.node_tree.nodes = _Nodes()
        self.node_tree.links = _Links()


def _material_with_principled():
    mat = _Material()
    bsdf = mat.node_tree.nodes.new('ShaderNodeBsdfPrincipled')
    return mat, bsdf


def _node_names(mat):
    return {n.name for n in mat.node_tree.nodes}


@pytest.fixture(autouse=True)
def _no_layout(monkeypatch):
    monkeypatch.setattr(sf, 'auto_layout', lambda nodes, links: None)


# ---------------------------------------------------------------------------
# Chain walker
# ---------------------------------------------------------------------------

class TestColorChainHasSwizzleSource:
    def test_unlinked_base_color_is_a_material_constant(self):
        _, bsdf = _material_with_principled()
        assert sf._color_chain_has_swizzle_source(bsdf.inputs['Base Color']) is False

    def test_constant_rgb_chain_has_no_source(self):
        mat, bsdf = _material_with_principled()
        rgb = mat.node_tree.nodes.new('ShaderNodeRGB')
        mat.node_tree.links.new(rgb.outputs[0], bsdf.inputs['Base Color'])
        assert sf._color_chain_has_swizzle_source(bsdf.inputs['Base Color']) is False

    def test_image_texture_is_a_source(self):
        mat, bsdf = _material_with_principled()
        tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
        mat.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        assert sf._color_chain_has_swizzle_source(bsdf.inputs['Base Color']) is True

    def test_vertex_colour_attribute_behind_a_mix_is_a_source(self):
        mat, bsdf = _material_with_principled()
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        attr = nodes.new('ShaderNodeAttribute')
        rgb = nodes.new('ShaderNodeRGB')
        mix = nodes.new('ShaderNodeMixRGB')
        links.new(attr.outputs['Color'], mix.inputs['Color1'])
        links.new(rgb.outputs[0], mix.inputs['Color2'])
        links.new(mix.outputs[0], bsdf.inputs['Base Color'])
        assert sf._color_chain_has_swizzle_source(bsdf.inputs['Base Color']) is True

    def test_walk_terminates_on_a_cycle(self):
        mat, bsdf = _material_with_principled()
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        mix_a = nodes.new('ShaderNodeMixRGB')
        mix_b = nodes.new('ShaderNodeMixRGB')
        links.new(mix_a.outputs[0], mix_b.inputs['Color1'])
        links.new(mix_b.outputs[0], mix_a.inputs['Color1'])
        links.new(mix_a.outputs[0], bsdf.inputs['Base Color'])
        assert sf._color_chain_has_swizzle_source(bsdf.inputs['Base Color']) is False


# ---------------------------------------------------------------------------
# Insertion
# ---------------------------------------------------------------------------

class TestInsertShinyFilter:
    def test_flat_material_colour_gets_brightness_only(self):
        mat, bsdf = _material_with_principled()
        sf.insert_shiny_filter(mat, MagicMock(), MagicMock(), MagicMock())
        names = _node_names(mat)
        assert 'shiny_bright_mix' in names
        assert 'shiny_bright_shader' in names
        assert 'shiny_route_mix' not in names
        assert 'shiny_route_shader' not in names
        # The bright mix now drives Base Color, fed from an RGB node holding
        # the socket's former default.
        base = bsdf.inputs['Base Color']
        assert base.is_linked
        assert base.links[0].from_node.name == 'shiny_bright_mix'

    def test_textured_material_gets_both_stages(self):
        mat, bsdf = _material_with_principled()
        tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
        mat.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
        sf.insert_shiny_filter(mat, MagicMock(), MagicMock(), MagicMock())
        names = _node_names(mat)
        assert {'shiny_route_mix', 'shiny_route_shader',
                'shiny_bright_mix', 'shiny_bright_shader'} <= names

    def test_vertex_coloured_material_gets_both_stages(self):
        mat, bsdf = _material_with_principled()
        attr = mat.node_tree.nodes.new('ShaderNodeAttribute')
        mat.node_tree.links.new(attr.outputs['Color'], bsdf.inputs['Base Color'])
        sf.insert_shiny_filter(mat, MagicMock(), MagicMock(), MagicMock())
        names = _node_names(mat)
        assert {'shiny_route_mix', 'shiny_bright_mix'} <= names

    def test_second_call_is_a_no_op(self):
        mat, _ = _material_with_principled()
        sf.insert_shiny_filter(mat, MagicMock(), MagicMock(), MagicMock())
        count = len(mat.node_tree.nodes)
        sf.insert_shiny_filter(mat, MagicMock(), MagicMock(), MagicMock())
        assert len(mat.node_tree.nodes) == count
