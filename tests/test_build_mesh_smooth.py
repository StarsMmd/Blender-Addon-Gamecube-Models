"""Regression test: imported meshes with custom split normals must have
their polygons marked use_smooth=True.

Background: in Blender 4.1+, polygons default to use_smooth=False (flat).
Flat-shaded polygons silently ignore custom split normals set via
mesh_data.normals_split_custom_set(). Before this fix, importing any model
with per-vertex normals produced a flat-shaded mesh that looked faceted —
most visible on smooth, high-density geometry like the Greninja
tongue/scarf reported on 2026-04-13.
"""
from unittest.mock import MagicMock, patch

from importer.phases.build_blender.helpers.meshes import _build_mesh
from shared.IR.geometry import IRMesh
from shared.IR.skeleton import IRModel


def _make_polys(n):
    polys = []
    for _ in range(n):
        p = MagicMock()
        p.use_smooth = False
        polys.append(p)
    return polys


def _build_args(ir_mesh, n_polys):
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

    ir_model = IRModel(name="test_model", bones=[])

    return mesh_data, mesh_obj, armature, ir_model


def test_polygons_marked_smooth_when_normals_present():
    """Polygons must be smooth-shaded when ir_mesh has per-loop normals."""
    n_polys = 4
    ir_mesh = IRMesh(
        name="m0",
        vertices=[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
        faces=[[0, 1, 2], [0, 2, 3]],
        normals=[(0, 0, 1)] * 6,
    )
    mesh_data, mesh_obj, armature, ir_model = _build_args(ir_mesh, n_polys)

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

        _build_mesh(ir_mesh, ir_model, armature, image_cache={},
                    logger=MagicMock(), mesh_idx=0)

    assert all(p.use_smooth is True for p in mesh_data.polygons), (
        "Every polygon should be marked smooth when normals are present"
    )
    mesh_data.normals_split_custom_set.assert_called_once_with(ir_mesh.normals)


def test_polygons_left_flat_when_no_normals():
    """Polygons remain flat-shaded when ir_mesh.normals is None."""
    n_polys = 4
    ir_mesh = IRMesh(
        name="m0",
        vertices=[(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)],
        faces=[[0, 1, 2], [0, 2, 3]],
        normals=None,
    )
    mesh_data, mesh_obj, armature, ir_model = _build_args(ir_mesh, n_polys)

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

        _build_mesh(ir_mesh, ir_model, armature, image_cache={},
                    logger=MagicMock(), mesh_idx=0)

    assert all(p.use_smooth is False for p in mesh_data.polygons), (
        "Polygons should remain flat when no normals are provided"
    )
    mesh_data.normals_split_custom_set.assert_not_called()
