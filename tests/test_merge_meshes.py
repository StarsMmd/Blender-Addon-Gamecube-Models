"""Tests for exporter/phases/describe_blender/helpers/merge_meshes.py."""
from exporter.phases.plan.helpers.merge_meshes import merge_meshes
from shared.IR.geometry import IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights, IRShapeKey
from shared.IR.enums import SkinType


def _make_mesh(name, verts, faces, material=None, bone_idx=0, uvs=None,
               colors=None, normals=None, weights=None, shape_keys=None,
               is_hidden=False, cull_front=False, cull_back=False,
               local_matrix=None):
    return IRMesh(
        name=name,
        vertices=list(verts),
        faces=[list(f) for f in faces],
        uv_layers=list(uvs) if uvs else [],
        color_layers=list(colors) if colors else [],
        normals=list(normals) if normals is not None else None,
        material=material,
        bone_weights=weights,
        shape_keys=list(shape_keys) if shape_keys else None,
        is_hidden=is_hidden,
        parent_bone_index=bone_idx,
        local_matrix=local_matrix,
        cull_front=cull_front,
        cull_back=cull_back,
    )


class TestMergeMeshes:

    def test_single_mesh_passthrough(self):
        mat = object()
        m = _make_mesh("a", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [[0, 1, 2]], material=mat)
        out = merge_meshes([m])
        assert len(out) == 1
        assert out[0].name == "a"

    def test_merges_same_bone_and_material(self):
        mat = object()
        a = _make_mesh("a", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [[0, 1, 2]], material=mat)
        b = _make_mesh("b", [(2, 0, 0), (3, 0, 0), (2, 1, 0)], [[0, 1, 2]], material=mat)
        out = merge_meshes([a, b])
        assert len(out) == 1
        # Vertices concatenated
        assert out[0].vertices == [(0, 0, 0), (1, 0, 0), (0, 1, 0),
                                    (2, 0, 0), (3, 0, 0), (2, 1, 0)]
        # Face indices on the second mesh offset by 3
        assert out[0].faces == [[0, 1, 2], [3, 4, 5]]

    def test_different_materials_stay_separate(self):
        m1, m2 = object(), object()
        a = _make_mesh("a", [(0, 0, 0)], [], material=m1)
        b = _make_mesh("b", [(1, 0, 0)], [], material=m2)
        out = merge_meshes([a, b])
        assert len(out) == 2

    def test_different_parent_bones_stay_separate(self):
        mat = object()
        a = _make_mesh("a", [(0, 0, 0)], [], material=mat, bone_idx=0)
        b = _make_mesh("b", [(1, 0, 0)], [], material=mat, bone_idx=5)
        out = merge_meshes([a, b])
        assert len(out) == 2

    def test_shape_key_meshes_passed_through(self):
        mat = object()
        sk = IRShapeKey(name="smile", vertex_positions=[(0, 0, 0)])
        a = _make_mesh("a", [(0, 0, 0)], [], material=mat, shape_keys=[sk])
        b = _make_mesh("b", [(1, 0, 0)], [], material=mat)
        out = merge_meshes([a, b])
        # Shape-key mesh passes through unmerged, regular mesh stands alone
        assert len(out) == 2

    def test_uv_layers_concatenate(self):
        mat = object()
        uv_a = IRUVLayer(name="UV", uvs=[(0, 0), (1, 0), (0, 1)])
        uv_b = IRUVLayer(name="UV", uvs=[(0.5, 0), (1, 0.5), (0, 1)])
        a = _make_mesh("a", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [[0, 1, 2]],
                       material=mat, uvs=[uv_a])
        b = _make_mesh("b", [(2, 0, 0), (3, 0, 0), (2, 1, 0)], [[0, 1, 2]],
                       material=mat, uvs=[uv_b])
        out = merge_meshes([a, b])
        assert len(out) == 1
        assert out[0].uv_layers[0].uvs == [(0, 0), (1, 0), (0, 1),
                                            (0.5, 0), (1, 0.5), (0, 1)]

    def test_mismatched_uv_layers_stay_separate(self):
        mat = object()
        a = _make_mesh("a", [(0, 0, 0)], [], material=mat,
                       uvs=[IRUVLayer(name="UV0", uvs=[(0, 0)])])
        b = _make_mesh("b", [(1, 0, 0)], [], material=mat,
                       uvs=[IRUVLayer(name="UV1", uvs=[(0, 0)])])
        out = merge_meshes([a, b])
        assert len(out) == 2

    def test_weighted_assignments_offset(self):
        mat = object()
        wa = IRBoneWeights(
            type=SkinType.WEIGHTED,
            assignments=[(0, [("bone_a", 1.0)]), (1, [("bone_a", 1.0)])],
        )
        wb = IRBoneWeights(
            type=SkinType.WEIGHTED,
            assignments=[(0, [("bone_b", 1.0)]), (1, [("bone_b", 1.0)])],
        )
        a = _make_mesh("a", [(0, 0, 0), (1, 0, 0)], [], material=mat, weights=wa)
        b = _make_mesh("b", [(2, 0, 0), (3, 0, 0)], [], material=mat, weights=wb)
        out = merge_meshes([a, b])
        assert len(out) == 1
        assignments = out[0].bone_weights.assignments
        # b's vertex indices shift by 2
        assert assignments == [
            (0, [("bone_a", 1.0)]),
            (1, [("bone_a", 1.0)]),
            (2, [("bone_b", 1.0)]),
            (3, [("bone_b", 1.0)]),
        ]

    def test_different_skin_types_stay_separate(self):
        mat = object()
        wa = IRBoneWeights(type=SkinType.SINGLE_BONE, bone_name="bone_a")
        wb = IRBoneWeights(type=SkinType.SINGLE_BONE, bone_name="bone_b")
        a = _make_mesh("a", [(0, 0, 0)], [], material=mat, weights=wa)
        b = _make_mesh("b", [(1, 0, 0)], [], material=mat, weights=wb)
        out = merge_meshes([a, b])
        # Different SINGLE_BONE targets cannot merge — shape key mismatch
        assert len(out) == 2

    def test_parallel_list_tracked(self):
        mat = object()
        a = _make_mesh("a", [(0, 0, 0)], [], material=mat)
        b = _make_mesh("b", [(1, 0, 0)], [], material=mat)
        c_mat = object()
        c = _make_mesh("c", [(2, 0, 0)], [], material=c_mat)
        parallel = ["mat_a", "mat_b", "mat_c"]
        merged, merged_parallel = merge_meshes([a, b, c], parallel=parallel)
        assert len(merged) == 2
        # Seed of first group is 'a' so parallel entry is 'mat_a'
        assert merged_parallel == ["mat_a", "mat_c"]

    def test_parallel_length_mismatch_raises(self):
        mat = object()
        a = _make_mesh("a", [(0, 0, 0)], [], material=mat)
        b = _make_mesh("b", [(1, 0, 0)], [], material=mat)
        import pytest
        with pytest.raises(ValueError):
            merge_meshes([a, b], parallel=["only_one"])

    def test_input_meshes_not_mutated(self):
        mat = object()
        a = _make_mesh("a", [(0, 0, 0), (1, 0, 0), (0, 1, 0)], [[0, 1, 2]], material=mat)
        b = _make_mesh("b", [(2, 0, 0), (3, 0, 0), (2, 1, 0)], [[0, 1, 2]], material=mat)
        before_a_verts = list(a.vertices)
        before_b_verts = list(b.vertices)
        merge_meshes([a, b])
        assert a.vertices == before_a_verts
        assert b.vertices == before_b_verts

    def test_hidden_flag_mismatch_stays_separate(self):
        mat = object()
        a = _make_mesh("a", [(0, 0, 0)], [], material=mat, is_hidden=True)
        b = _make_mesh("b", [(1, 0, 0)], [], material=mat, is_hidden=False)
        out = merge_meshes([a, b])
        assert len(out) == 2
