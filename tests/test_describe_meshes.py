"""Tests for phases/describe/meshes.py — geometry extraction helpers."""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from importer.phases.describe.helpers.meshes import (
    _validate_mesh, _extract_uv_layer, _extract_normals, describe_meshes,
    _walk_joints, _walk_mesh_chain, _describe_pobj,
)
from shared.IR.geometry import IRUVLayer
from shared.Constants.gx import GX_VA_POS
from shared.helpers.logger import StubLogger


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


# --- Helpers for material cache tests ---

def _make_bone(name='bone'):
    return SimpleNamespace(
        name=name, flags=0,
        world_matrix=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
        inverse_bind_matrix=None, parent_index=None, mesh_indices=[],
        instance_child_bone_index=None,
    )


def _make_pobj(address=200):
    """Minimal PObject with one triangle."""
    return SimpleNamespace(
        address=address,
        name='prim',
        vertex_list=SimpleNamespace(vertices=[
            SimpleNamespace(attribute=GX_VA_POS, isTexture=lambda: False),
        ]),
        flags=0,
        sources=[[(0, 0, 0), (1, 0, 0), (0, 1, 0)]],
        face_lists=[[[0, 1, 2]]],
        property=None,
        next=None,
    )


def _make_mesh_node(address, mobject, pobj):
    """Minimal DObject (Mesh node)."""
    return SimpleNamespace(
        address=address,
        mobject=mobject,
        pobject=pobj,
        next=None,
    )


def _make_joint(address, mesh_node):
    """Minimal Joint pointing to a mesh chain."""
    return SimpleNamespace(
        address=address,
        flags=0,
        child=None,
        next=None,
        property=SimpleNamespace(pobject=mesh_node.pobject) if mesh_node is None else mesh_node,
    )


class TestMaterialCache:

    @patch('importer.phases.describe.helpers.materials.describe_material')
    def test_same_mobject_reuses_ir_material(self, mock_describe_mat):
        """Two DObjects with the same mobject.address share one IRMaterial."""
        shared_material = SimpleNamespace(texture_layers=[])
        mock_describe_mat.return_value = shared_material

        mobject = SimpleNamespace(address=0x100)

        pobj_a = _make_pobj(address=200)
        pobj_b = _make_pobj(address=300)
        mesh_a = _make_mesh_node(address=50, mobject=mobject, pobj=pobj_a)
        mesh_b = _make_mesh_node(address=60, mobject=mobject, pobj=pobj_b)
        mesh_a.next = mesh_b  # chain them

        joint = SimpleNamespace(
            address=0, flags=0, child=None, next=None,
            property=mesh_a,
        )

        bones = [_make_bone()]
        joint_to_bone_index = {0: 0}

        meshes = describe_meshes(joint, bones, joint_to_bone_index)

        assert len(meshes) == 2
        assert meshes[0].material is meshes[1].material
        mock_describe_mat.assert_called_once()

    @patch('importer.phases.describe.helpers.materials.describe_material')
    def test_different_mobjects_get_different_materials(self, mock_describe_mat):
        """Two DObjects with different mobject addresses get separate IRMaterials."""
        mat_a = SimpleNamespace(texture_layers=[])
        mat_b = SimpleNamespace(texture_layers=[])
        mock_describe_mat.side_effect = [mat_a, mat_b]

        mob_a = SimpleNamespace(address=0x100)
        mob_b = SimpleNamespace(address=0x200)

        pobj_a = _make_pobj(address=200)
        pobj_b = _make_pobj(address=300)
        mesh_a = _make_mesh_node(address=50, mobject=mob_a, pobj=pobj_a)
        mesh_b = _make_mesh_node(address=60, mobject=mob_b, pobj=pobj_b)
        mesh_a.next = mesh_b

        joint = SimpleNamespace(
            address=0, flags=0, child=None, next=None,
            property=mesh_a,
        )

        bones = [_make_bone()]
        joint_to_bone_index = {0: 0}

        meshes = describe_meshes(joint, bones, joint_to_bone_index)

        assert len(meshes) == 2
        assert meshes[0].material is not meshes[1].material
        assert mock_describe_mat.call_count == 2

    def test_describe_pobj_direct_call(self):
        """_describe_pobj is callable at module level with explicit args."""
        pobj = _make_pobj(address=200)
        joint = SimpleNamespace(address=0, flags=0)
        bones = [_make_bone()]
        mesh = _describe_pobj(
            pobj, joint, bone_index=0, count=0,
            bones=bones, joint_to_bone_index={0: 0},
            options={}, image_cache={}, logger=StubLogger(),
            ir_material=None,
        )
        assert mesh is not None
        assert mesh.name == 'prim'
        assert len(mesh.vertices) == 3
        assert mesh.faces == [[0, 1, 2]]
        assert mesh.material is None

    def test_describe_pobj_returns_none_without_position(self):
        """No GX_VA_POS attribute → returns None."""
        pobj = SimpleNamespace(
            address=200, name='x', flags=0, sources=[], face_lists=[],
            property=None, next=None,
            vertex_list=SimpleNamespace(vertices=[]),
        )
        joint = SimpleNamespace(address=0, flags=0)
        result = _describe_pobj(
            pobj, joint, 0, 0, [_make_bone()], {0: 0},
            {}, {}, StubLogger(),
        )
        assert result is None

    def test_walk_mesh_chain_appends_meshes(self):
        """_walk_mesh_chain walks DObject linked list and appends to meshes list."""
        pobj_a = _make_pobj(address=200)
        pobj_b = _make_pobj(address=300)
        mesh_a = _make_mesh_node(50, mobject=None, pobj=pobj_a)
        mesh_b = _make_mesh_node(60, mobject=None, pobj=pobj_b)
        mesh_a.next = mesh_b

        joint = SimpleNamespace(address=0, flags=0)
        bones = [_make_bone()]
        meshes = []
        _walk_mesh_chain(
            mesh_a, joint, bone_index=0,
            bones=bones, joint_to_bone_index={0: 0},
            options={}, image_cache={}, logger=StubLogger(),
            meshes=meshes, material_cache={},
        )
        assert len(meshes) == 2
        assert bones[0].mesh_indices == [0, 1]

    def test_walk_joints_recurses_children_and_siblings(self):
        """_walk_joints visits child + next, populating meshes from each."""
        # Build: root -> child(meshes) -> sibling(meshes)
        pobj_c = _make_pobj(address=200)
        pobj_s = _make_pobj(address=300)
        mesh_c = _make_mesh_node(50, mobject=None, pobj=pobj_c)
        mesh_s = _make_mesh_node(60, mobject=None, pobj=pobj_s)

        child = SimpleNamespace(address=1, flags=0, child=None, next=None,
                                property=mesh_c)
        sibling = SimpleNamespace(address=2, flags=0, child=None, next=None,
                                  property=mesh_s)
        child.next = sibling
        root = SimpleNamespace(address=0, flags=0, child=child, next=None,
                               property=None)

        bones = [_make_bone('r'), _make_bone('c'), _make_bone('s')]
        meshes = []
        _walk_joints(
            root, bones, {0: 0, 1: 1, 2: 2}, {}, {}, StubLogger(),
            meshes, {},
        )
        assert len(meshes) == 2
        assert bones[1].mesh_indices == [0]
        assert bones[2].mesh_indices == [1]

    def test_none_mobject_no_error(self):
        """DObject with mobject=None produces mesh with material=None."""
        pobj = _make_pobj(address=200)
        mesh_node = _make_mesh_node(address=50, mobject=None, pobj=pobj)

        joint = SimpleNamespace(
            address=0, flags=0, child=None, next=None,
            property=mesh_node,
        )

        bones = [_make_bone()]
        joint_to_bone_index = {0: 0}

        meshes = describe_meshes(joint, bones, joint_to_bone_index)

        assert len(meshes) == 1
        assert meshes[0].material is None
