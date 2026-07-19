"""Pre-process guard: reject materials that bind more than 8 image textures.

GX exposes 8 texture units per material (GX_MAX_TEXMAP). The engine's
render-time material setup (`HSD_TObjSetup`) asserts and halts the console
when a material activates a 9th texgen — a hard crash, not a silent
misrender. Arbitrary GLB/FBX rips can stack many image nodes on one
material, so the exporter rejects any material over the cap at validation
time. The count is a proxy: image-texture nodes with an assigned image.
"""
import pytest


class _FakeNode:
    def __init__(self, bl_idname, image=None):
        self.bl_idname = bl_idname
        self.image = image


class _FakeNodeTree:
    def __init__(self, nodes):
        self.nodes = nodes


class _FakeMaterial:
    def __init__(self, name, nodes, use_nodes=True):
        self.name = name
        self.use_nodes = use_nodes
        self.node_tree = _FakeNodeTree(nodes)


# --- _count_material_image_textures ----------------------------------------

def test_count_counts_only_image_nodes_with_image():
    from exporter.phases.pre_process.pre_process import _count_material_image_textures
    mat = _FakeMaterial("m", [
        _FakeNode('ShaderNodeTexImage', object()),
        _FakeNode('ShaderNodeTexImage', object()),
        _FakeNode('ShaderNodeBsdfPrincipled'),
    ])
    assert _count_material_image_textures(mat) == 2


def test_count_ignores_image_nodes_without_image():
    from exporter.phases.pre_process.pre_process import _count_material_image_textures
    mat = _FakeMaterial("m", [
        _FakeNode('ShaderNodeTexImage', None),
        _FakeNode('ShaderNodeTexImage', object()),
    ])
    assert _count_material_image_textures(mat) == 1


def test_count_zero_when_nodes_disabled():
    from exporter.phases.pre_process.pre_process import _count_material_image_textures
    mat = _FakeMaterial("m", [_FakeNode('ShaderNodeTexImage', object())],
                        use_nodes=False)
    assert _count_material_image_textures(mat) == 0


# --- _check_material_texture_count -----------------------------------------

def test_guard_empty_is_fine():
    from exporter.phases.pre_process.pre_process import _check_material_texture_count
    _check_material_texture_count([])  # no raise


def test_guard_accepts_exactly_eight():
    from exporter.phases.pre_process.pre_process import _check_material_texture_count
    _check_material_texture_count([("mat", 8)])  # no raise — 8 is the cap


def test_guard_rejects_nine():
    from exporter.phases.pre_process.pre_process import _check_material_texture_count
    with pytest.raises(ValueError) as exc:
        _check_material_texture_count([("skin", 9)])
    msg = str(exc.value)
    assert "skin" in msg
    assert "8" in msg


def test_guard_collects_all_offenders():
    from exporter.phases.pre_process.pre_process import _check_material_texture_count
    with pytest.raises(ValueError) as exc:
        _check_material_texture_count([
            ("body", 12),
            ("eyes", 2),   # fine
            ("cloth", 9),
        ])
    msg = str(exc.value)
    assert "body" in msg and "cloth" in msg
    assert "eyes" not in msg
