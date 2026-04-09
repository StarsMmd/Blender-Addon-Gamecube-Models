"""Tests for envelope display list splitting in the compose phase.

When a mesh has >10 unique bone weight combinations (envelopes), the
GX hardware's 10 matrix slots require splitting into multiple PObjects.
"""
import pytest

from exporter.phases.compose.helpers.meshes import (
    _triangulate_faces,
    _partition_triangles_by_envelope,
    _build_split_envelope_map,
    _build_envelope_map,
)


# ---------------------------------------------------------------------------
# _triangulate_faces
# ---------------------------------------------------------------------------

class TestTriangulateFaces:
    def test_triangles_pass_through(self):
        faces = [[0, 1, 2], [3, 4, 5]]
        tris, loops = _triangulate_faces(faces)
        assert tris == [[0, 1, 2], [3, 4, 5]]
        assert loops == [[0, 1, 2], [3, 4, 5]]

    def test_quad_splits_into_two(self):
        faces = [[0, 1, 2, 3]]
        tris, loops = _triangulate_faces(faces)
        assert len(tris) == 2
        assert tris[0] == [0, 1, 2]
        assert tris[1] == [0, 2, 3]

    def test_ngon_fans_from_vertex_0(self):
        faces = [[0, 1, 2, 3, 4]]
        tris, loops = _triangulate_faces(faces)
        assert len(tris) == 3
        assert tris[0] == [0, 1, 2]
        assert tris[1] == [0, 2, 3]
        assert tris[2] == [0, 3, 4]

    def test_empty_faces(self):
        tris, loops = _triangulate_faces([])
        assert tris == []
        assert loops == []

    def test_loop_indices_track_original_positions(self):
        # Two triangles: loops 0-2 for face 0, loops 3-5 for face 1
        faces = [[10, 11, 12], [20, 21, 22]]
        tris, loops = _triangulate_faces(faces)
        assert loops[0] == [0, 1, 2]
        assert loops[1] == [3, 4, 5]

    def test_quad_loop_indices(self):
        faces = [[0, 1, 2, 3]]
        tris, loops = _triangulate_faces(faces)
        # Quad has 4 loops: 0, 1, 2, 3
        assert loops[0] == [0, 1, 2]  # tri 1: verts 0,1,2
        assert loops[1] == [0, 2, 3]  # tri 2: verts 0,2,3


# ---------------------------------------------------------------------------
# _partition_triangles_by_envelope
# ---------------------------------------------------------------------------

class TestPartitionTrianglesByEnvelope:
    def _make_env_map(self, vertex_to_env, num_envelopes):
        """Helper to build a minimal envelope_map dict."""
        return {
            'vertex_to_env': vertex_to_env,
            'envelopes': [[(f'bone_{i}', 1.0)] for i in range(num_envelopes)],
        }

    def test_single_group_under_limit(self):
        # 3 triangles using 5 envelopes — fits in one group
        tris = [[0, 1, 2], [3, 4, 5], [6, 7, 8]]
        loops = [[0, 1, 2], [3, 4, 5], [6, 7, 8]]
        vtx_to_env = {i: i % 5 for i in range(9)}
        env_map = self._make_env_map(vtx_to_env, 5)

        groups = _partition_triangles_by_envelope(tris, loops, env_map)
        assert len(groups) == 1
        assert len(groups[0]['triangles']) == 3

    def test_split_at_11_envelopes(self):
        # 11 triangles, each using a unique envelope for vertex 0
        tris = [[i * 3, i * 3 + 1, i * 3 + 2] for i in range(11)]
        loops = [[i * 3, i * 3 + 1, i * 3 + 2] for i in range(11)]
        vtx_to_env = {}
        for i in range(11):
            vtx_to_env[i * 3] = i      # unique envelope per triangle
            vtx_to_env[i * 3 + 1] = 0  # shared
            vtx_to_env[i * 3 + 2] = 0  # shared
        env_map = self._make_env_map(vtx_to_env, 11)

        groups = _partition_triangles_by_envelope(tris, loops, env_map)
        assert len(groups) == 2
        for g in groups:
            assert len(g['envelope_indices']) <= 10

    def test_exactly_10_envelopes_no_split(self):
        tris = [[i * 3, i * 3 + 1, i * 3 + 2] for i in range(10)]
        loops = [[i * 3, i * 3 + 1, i * 3 + 2] for i in range(10)]
        vtx_to_env = {}
        for i in range(10):
            vtx_to_env[i * 3] = i
            vtx_to_env[i * 3 + 1] = 0
            vtx_to_env[i * 3 + 2] = 0
        env_map = self._make_env_map(vtx_to_env, 10)

        groups = _partition_triangles_by_envelope(tris, loops, env_map)
        assert len(groups) == 1

    def test_all_triangles_accounted_for(self):
        # 20 triangles with 15 envelopes
        tris = [[i * 3, i * 3 + 1, i * 3 + 2] for i in range(20)]
        loops = [[i * 3, i * 3 + 1, i * 3 + 2] for i in range(20)]
        vtx_to_env = {}
        for i in range(20):
            vtx_to_env[i * 3] = i % 15
            vtx_to_env[i * 3 + 1] = (i + 1) % 15
            vtx_to_env[i * 3 + 2] = (i + 2) % 15
        env_map = self._make_env_map(vtx_to_env, 15)

        groups = _partition_triangles_by_envelope(tris, loops, env_map)
        total_tris = sum(len(g['triangles']) for g in groups)
        assert total_tris == 20
        for g in groups:
            assert len(g['envelope_indices']) <= 10

    def test_best_fit_minimizes_groups(self):
        # Triangles that share envelopes should be packed together
        # 12 tris: first 6 use envs {0,1}, last 6 use envs {2,3}
        tris = [[i, i + 1, i + 2] for i in range(0, 36, 3)]
        loops = [[i, i + 1, i + 2] for i in range(0, 36, 3)]
        vtx_to_env = {}
        for i in range(18):  # first 6 tris (18 verts)
            vtx_to_env[i] = i % 2  # envs 0, 1
        for i in range(18, 36):  # last 6 tris
            vtx_to_env[i] = 2 + (i % 2)  # envs 2, 3
        env_map = self._make_env_map(vtx_to_env, 4)

        groups = _partition_triangles_by_envelope(tris, loops, env_map)
        # All 4 envelopes fit in one group
        assert len(groups) == 1

    def test_envelope_indices_sorted(self):
        tris = [[0, 1, 2]]
        loops = [[0, 1, 2]]
        vtx_to_env = {0: 5, 1: 2, 2: 8}
        env_map = self._make_env_map(vtx_to_env, 9)

        groups = _partition_triangles_by_envelope(tris, loops, env_map)
        assert groups[0]['envelope_indices'] == [2, 5, 8]

    def test_worst_case_disjoint_envelopes(self):
        # Each triangle uses 3 completely unique envelopes — no sharing
        # 4 triangles * 3 envs = 12 envs, needs 2 groups minimum
        tris = [[i * 3, i * 3 + 1, i * 3 + 2] for i in range(4)]
        loops = [[i * 3, i * 3 + 1, i * 3 + 2] for i in range(4)]
        vtx_to_env = {i: i for i in range(12)}  # all unique
        env_map = self._make_env_map(vtx_to_env, 12)

        groups = _partition_triangles_by_envelope(tris, loops, env_map)
        assert len(groups) >= 2
        for g in groups:
            assert len(g['envelope_indices']) <= 10


# ---------------------------------------------------------------------------
# _build_split_envelope_map
# ---------------------------------------------------------------------------

class TestBuildSplitEnvelopeMap:
    def test_basic_remapping(self):
        global_map = {
            'vertex_to_env': {0: 0, 1: 5, 2: 11, 3: 5},
            'envelopes': [
                [('bone_0', 1.0)] if i != 5 and i != 11 else
                [('bone_5', 0.5), ('bone_6', 0.5)] if i == 5 else
                [('bone_11', 1.0)]
                for i in range(12)
            ],
        }
        group_envs = [5, 11]
        group_tris = [[1, 2, 3]]  # uses verts 1, 2, 3

        local = _build_split_envelope_map(global_map, group_envs, group_tris)

        # Global env 5 → local 0, global env 11 → local 1
        assert local['vertex_to_env'][1] == 0  # was global 5
        assert local['vertex_to_env'][2] == 1  # was global 11
        assert local['vertex_to_env'][3] == 0  # was global 5
        assert 0 not in local['vertex_to_env']  # vert 0 not in group

        assert len(local['envelopes']) == 2
        assert local['envelopes'][0] == [('bone_5', 0.5), ('bone_6', 0.5)]
        assert local['envelopes'][1] == [('bone_11', 1.0)]

    def test_single_envelope(self):
        global_map = {
            'vertex_to_env': {0: 3, 1: 3, 2: 3},
            'envelopes': [[('bone_0', 1.0)]] * 4,
        }
        group_envs = [3]
        group_tris = [[0, 1, 2]]

        local = _build_split_envelope_map(global_map, group_envs, group_tris)
        assert local['vertex_to_env'] == {0: 0, 1: 0, 2: 0}
        assert len(local['envelopes']) == 1

    def test_preserves_envelope_order(self):
        global_map = {
            'vertex_to_env': {0: 8, 1: 2, 2: 5},
            'envelopes': [[('bone_%d' % i, 1.0)] for i in range(9)],
        }
        # group_envelope_indices are sorted: [2, 5, 8]
        group_envs = [2, 5, 8]
        group_tris = [[0, 1, 2]]

        local = _build_split_envelope_map(global_map, group_envs, group_tris)
        # local 0 = global 2, local 1 = global 5, local 2 = global 8
        assert local['vertex_to_env'][1] == 0  # was global 2
        assert local['vertex_to_env'][2] == 1  # was global 5
        assert local['vertex_to_env'][0] == 2  # was global 8
        assert local['envelopes'][0] == [('bone_2', 1.0)]
        assert local['envelopes'][1] == [('bone_5', 1.0)]
        assert local['envelopes'][2] == [('bone_8', 1.0)]
