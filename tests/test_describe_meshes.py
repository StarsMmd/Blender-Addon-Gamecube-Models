"""Tests for phases/describe/meshes.py — geometry extraction helpers."""
from importer.phases.describe.helpers.meshes import (
    _validate_mesh, _extract_uv_layer, _extract_normals,
)
from shared.IR.geometry import IRUVLayer


class TestValidateMesh:

    def test_removes_degenerate_faces(self):
        """Faces with duplicate vertex indices are removed."""
        faces = [[0, 1, 2], [0, 0, 1], [2, 3, 4]]
        face_lists = [[[10, 11, 12], [10, 10, 11], [12, 13, 14]]]
        pruned_lists, pruned_faces = _validate_mesh(face_lists, faces)
        assert len(pruned_faces) == 2
        assert pruned_faces[0] == [0, 1, 2]
        assert pruned_faces[1] == [2, 3, 4]

    def test_keeps_valid_faces(self):
        faces = [[0, 1, 2], [3, 4, 5]]
        face_lists = [faces[:]]
        pruned_lists, pruned_faces = _validate_mesh(face_lists, faces)
        assert len(pruned_faces) == 2

    def test_empty_input(self):
        _, pruned = _validate_mesh([[]], [])
        assert pruned == []


class TestExtractUVLayer:

    def test_uv_v_flip(self):
        """V coordinate is flipped (1 - v)."""
        source = [(0.5, 0.25), (0.0, 1.0), (1.0, 0.0)]
        face_list = [[0, 1, 2]]
        faces = [[0, 1, 2]]
        uv = _extract_uv_layer(source, face_list, faces, 0)
        assert isinstance(uv, IRUVLayer)
        assert uv.name == 'uvtex_0'
        assert len(uv.uvs) == 3
        # V should be flipped
        assert abs(uv.uvs[0][0] - 0.5) < 1e-6
        assert abs(uv.uvs[0][1] - 0.75) < 1e-6  # 1 - 0.25
        assert abs(uv.uvs[1][1] - 0.0) < 1e-6   # 1 - 1.0
        assert abs(uv.uvs[2][1] - 1.0) < 1e-6   # 1 - 0.0

    def test_multiple_faces(self):
        source = [(0, 0), (1, 0), (0, 1), (1, 1)]
        face_list = [[0, 1, 2], [1, 3, 2]]
        faces = [[0, 1, 2], [1, 3, 2]]
        uv = _extract_uv_layer(source, face_list, faces, 1)
        assert uv.name == 'uvtex_1'
        assert len(uv.uvs) == 6  # 2 faces * 3 verts


class TestExtractNormals:

    def test_basic_normals(self):
        """Normals are extracted and normalized per loop."""
        source = [(0, 0, 1), (0, 1, 0), (1, 0, 0)]
        face_list = [[0, 1, 2]]
        faces = [[0, 1, 2]]
        normals = _extract_normals(source, face_list, faces)
        assert len(normals) == 3
        # Already unit length, should be unchanged
        assert abs(normals[0][2] - 1.0) < 1e-6
        assert abs(normals[1][1] - 1.0) < 1e-6
        assert abs(normals[2][0] - 1.0) < 1e-6

    def test_normals_are_normalized(self):
        """Non-unit normals get normalized."""
        source = [(0, 0, 5)]  # length 5, should become (0, 0, 1)
        face_list = [[0]]
        faces = [[0]]
        normals = _extract_normals(source, face_list, faces)
        assert abs(normals[0][2] - 1.0) < 1e-6
