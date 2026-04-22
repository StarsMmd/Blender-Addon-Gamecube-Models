"""Regression test: imported meshes with custom split normals must have
their polygons marked use_smooth=True.

Background: in Blender 4.1+, polygons default to use_smooth=False (flat).
Flat-shaded polygons silently ignore custom split normals set via
mesh_data.normals_split_custom_set(). Without this fix, importing any
model with per-vertex normals produces a flat-shaded mesh that looks
faceted — most visible on smooth, high-density geometry.
"""
from unittest.mock import MagicMock, patch

from importer.phases.build_blender.helpers.meshes import _build_mesh
from shared.BR.meshes import BRMesh


def _make_polys(n):
    polys = []
    for _ in range(n):
        p = MagicMock()
        p.use_smooth = False
        polys.append(p)
    return polys


def _build_args(n_polys):
    """Set up the bpy mocks _build_mesh needs and return the call args."""
    mesh_data = MagicMock()
    mesh_data.polygons = _make_polys(n_polys)
    mesh_data.has_custom_normals = True
    mesh_data.uv_layers = MagicMock()
    mesh_data.color_attributes = MagicMock()
    mesh_data.materials = MagicMock()
    mesh_data.vertices = []

    mesh_obj = MagicMock()
    mesh_obj.data = mesh_data
    mesh_obj.material_slots = []
    mesh_obj.vertex_groups = MagicMock()

    armature = MagicMock()
    armature.data.bones = {}

    return mesh_data, mesh_obj, armature


def _make_br_mesh(**overrides):
    defaults = dict(
        name="m0",
        mesh_key="mesh_0_unknown",
        vertices=[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
        faces=[[0, 1, 2], [0, 2, 3]],
        normals=None,
    )
    defaults.update(overrides)
    return BRMesh(**defaults)


def test_polygons_marked_smooth_when_normals_present():
    """Polygons must be smooth-shaded when br_mesh has per-loop normals."""
    n_polys = 4
    br_mesh = _make_br_mesh(normals=[(0, 0, 1)] * 6)
    mesh_data, mesh_obj, armature = _build_args(n_polys)

    with patch(
        "importer.phases.build_blender.helpers.meshes.bpy"
    ) as bpy_mock, patch(
        "importer.phases.build_blender.helpers.meshes.Vector",
        side_effect=lambda x: x,
    ), patch(
        "importer.phases.build_blender.helpers.meshes.Matrix",
        side_effect=lambda x: x,
    ):
        bpy_mock.data.meshes.new.return_value = mesh_data
        bpy_mock.data.objects.new.return_value = mesh_obj
        bpy_mock.data.materials.new.return_value = MagicMock()

        _build_mesh(br_mesh, armature, logger=MagicMock(), mesh_idx=0)

    assert all(p.use_smooth is True for p in mesh_data.polygons), (
        "Every polygon should be marked smooth when normals are present"
    )
    mesh_data.normals_split_custom_set.assert_called_once_with(br_mesh.normals)


def test_polygons_left_flat_when_no_normals():
    """Polygons remain flat-shaded when br_mesh.normals is None."""
    n_polys = 4
    br_mesh = _make_br_mesh(normals=None)
    mesh_data, mesh_obj, armature = _build_args(n_polys)

    with patch(
        "importer.phases.build_blender.helpers.meshes.bpy"
    ) as bpy_mock, patch(
        "importer.phases.build_blender.helpers.meshes.Vector",
        side_effect=lambda x: x,
    ), patch(
        "importer.phases.build_blender.helpers.meshes.Matrix",
        side_effect=lambda x: x,
    ):
        bpy_mock.data.meshes.new.return_value = mesh_data
        bpy_mock.data.objects.new.return_value = mesh_obj
        bpy_mock.data.materials.new.return_value = MagicMock()

        _build_mesh(br_mesh, armature, logger=MagicMock(), mesh_idx=0)

    assert all(p.use_smooth is False for p in mesh_data.polygons), (
        "Polygons should remain flat when no normals are provided"
    )
    mesh_data.normals_split_custom_set.assert_not_called()
