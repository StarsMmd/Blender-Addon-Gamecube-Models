"""Tests for the un-deform ↔ stored-envelope contract in compose.

The compose phase writes an envelope list (bone + weight per combo) to disk
and separately un-deforms each vertex position into its bind pose. The game
re-applies the stored envelope at render time; if the un-deform used a
different weight blend than the stored envelope, the vertex drifts.

These tests lock the invariant in: whatever blend matrix the stored envelope
implies must be the exact inverse of the blend matrix used to un-deform the
vertex. Weight limiting and quantisation are the prepare script's job;
compose only renormalises against floating-point drift.
"""
from mathutils import Matrix, Vector

from exporter.phases.compose.helpers.meshes import (
    _build_envelope_map,
    _canonicalize_weights,
    _find_skeleton_bone,
    _undeform_vertices,
)
from shared.Constants.hsd import JOBJ_SKELETON, JOBJ_SKELETON_ROOT


def _identity_4x4():
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _translation_4x4(tx, ty, tz):
    return [
        [1.0, 0.0, 0.0, tx],
        [0.0, 1.0, 0.0, ty],
        [0.0, 0.0, 1.0, tz],
        [0.0, 0.0, 0.0, 1.0],
    ]


class _FakeBone:
    def __init__(self, name, world_matrix, inverse_bind_matrix, parent_index=None):
        self.name = name
        self.world_matrix = world_matrix
        self.inverse_bind_matrix = inverse_bind_matrix
        self.parent_index = parent_index
        self.flags = 0


def _make_skel():
    # Two bones, each at an offset, with identity IBM so the deform matrix
    # equals the bone's world matrix.
    return [
        _FakeBone("BoneA", _translation_4x4(2.0, 0.0, 0.0), _identity_4x4()),
        _FakeBone("BoneB", _translation_4x4(0.0, 3.0, 0.0), _identity_4x4(),
                  parent_index=0),
    ]


def _deform_with(envelopes, vertex_to_env, bones, bone_name_to_index, verts):
    """Apply the stored envelope blend (forward direction) to each vertex."""
    matrices = []
    for weight_list in envelopes:
        m = Matrix([[0.0] * 4 for _ in range(4)])
        for bone_name, w in weight_list:
            bone_idx = bone_name_to_index[bone_name]
            bw = Matrix(bones[bone_idx].world_matrix)
            ibm = Matrix(bones[bone_idx].inverse_bind_matrix)
            contrib = bw @ ibm
            for i in range(4):
                for j in range(4):
                    m[i][j] += w * contrib[i][j]
        matrices.append(m)

    out = []
    for idx, v in enumerate(verts):
        env_idx = vertex_to_env[idx]
        p = matrices[env_idx] @ Vector(v)
        out.append((p[0], p[1], p[2]))
    return out


# ---------------------------------------------------------------------------
# _canonicalize_weights
# ---------------------------------------------------------------------------

class TestCanonicalizeWeights:
    def test_preserves_unit_sum_weights(self):
        canon, key = _canonicalize_weights([('A', 0.5), ('B', 0.5)])
        assert canon == [('A', 0.5), ('B', 0.5)]
        assert key == (('A', 0.5), ('B', 0.5))

    def test_renormalises_off_by_5_percent(self):
        canon, _ = _canonicalize_weights([('A', 0.95)])
        assert canon == [('A', 1.0)]

    def test_preserves_fine_weights(self):
        canon, _ = _canonicalize_weights([('A', 0.6), ('B', 0.4)])
        assert canon == [('A', 0.6), ('B', 0.4)]

    def test_preserves_minor_weight_below_quartile(self):
        # Regression for the 25% quantiser era: (0.85, 0.15) used to
        # collapse to (1.0, 0.0), rigidly-snapping vertices near chain
        # joints and flinging distal mesh off-bone.
        canon, _ = _canonicalize_weights([('A', 0.85), ('B', 0.15)])
        assert canon == [('A', 0.85), ('B', 0.15)]

    def test_key_is_sorted_by_bone_name(self):
        _, key1 = _canonicalize_weights([('Z', 0.5), ('A', 0.5)])
        _, key2 = _canonicalize_weights([('A', 0.5), ('Z', 0.5)])
        assert key1 == key2


# ---------------------------------------------------------------------------
# _build_envelope_map — stores canonical (quantised) weights
# ---------------------------------------------------------------------------

class TestEnvelopeMapStoresCanonicalWeights:
    def test_identical_weights_collapse_to_one_envelope(self):
        assignments = [
            (0, [('A', 0.6), ('B', 0.4)]),
            (1, [('A', 0.6), ('B', 0.4)]),
        ]
        result = _build_envelope_map(assignments, {'A': 0, 'B': 1})
        assert len(result['envelopes']) == 1
        stored = dict(result['envelopes'][0])
        assert stored == {'A': 0.6, 'B': 0.4}

    def test_distinct_weights_stay_distinct(self):
        # Vertices with different weight blends must get different envelopes
        # now that we no longer quantise them together.
        assignments = [
            (0, [('A', 0.6), ('B', 0.4)]),
            (1, [('A', 0.4), ('B', 0.6)]),
        ]
        result = _build_envelope_map(assignments, {'A': 0, 'B': 1})
        assert len(result['envelopes']) == 2
        assert result['vertex_to_env'][0] != result['vertex_to_env'][1]

    def test_renormalised_weights_stored(self):
        # Weight sum = 0.9 → renormalise → (A=1.0)
        assignments = [(0, [('A', 0.9)])]
        result = _build_envelope_map(assignments, {'A': 0})
        stored = dict(result['envelopes'][0])
        assert stored == {'A': 1.0}


# ---------------------------------------------------------------------------
# _undeform_vertices ↔ stored envelope round-trip
# ---------------------------------------------------------------------------

class TestUndeformRoundTrip:
    """The core regression: un-deform + re-deform must be the identity."""

    def test_single_vertex_roundtrip(self):
        bones = _make_skel()
        bone_map = {'A': 0, 'B': 1}
        # Rename so the fake skeleton's bone_name_to_index lookup works
        bones[0].name = 'A'
        bones[1].name = 'B'

        assignments = [(0, [('A', 1.0)])]
        env_map = _build_envelope_map(assignments, bone_map)

        world = [(5.0, 1.0, 0.0)]
        bind = _undeform_vertices(world, env_map, bones, bone_map, 0, None)
        redeformed = _deform_with(env_map['envelopes'], env_map['vertex_to_env'],
                                  bones, bone_map, bind)
        assert redeformed[0] == world[0] or (
            abs(redeformed[0][0] - world[0][0]) < 1e-6
            and abs(redeformed[0][1] - world[0][1]) < 1e-6
            and abs(redeformed[0][2] - world[0][2]) < 1e-6
        )

    def test_two_distinct_weight_vertices_roundtrip(self):
        """Two vertices with different raw weight blends must each round-trip
        through their own envelope entry."""
        bones = _make_skel()
        bones[0].name = 'A'
        bones[1].name = 'B'
        bone_map = {'A': 0, 'B': 1}

        assignments = [
            (0, [('A', 0.6), ('B', 0.4)]),
            (1, [('A', 0.4), ('B', 0.6)]),
        ]
        world = [(1.0, 2.0, 3.0), (-1.0, 0.5, 4.0)]

        env_map = _build_envelope_map(assignments, bone_map)
        assert env_map['vertex_to_env'][0] != env_map['vertex_to_env'][1]

        bind = _undeform_vertices(world, env_map, bones, bone_map, 0, None)
        redeformed = _deform_with(env_map['envelopes'], env_map['vertex_to_env'],
                                  bones, bone_map, bind)

        for orig, back in zip(world, redeformed):
            assert abs(orig[0] - back[0]) < 1e-4
            assert abs(orig[1] - back[1]) < 1e-4
            assert abs(orig[2] - back[2]) < 1e-4

    def test_renormalisation_consistent_between_map_and_undeform(self):
        """Vertex weights summing to 0.95 must be renormalised identically
        in both the stored envelope and the un-deform matrix."""
        bones = _make_skel()
        bones[0].name = 'A'
        bones[1].name = 'B'
        bone_map = {'A': 0, 'B': 1}

        assignments = [(0, [('A', 0.475), ('B', 0.475)])]  # sum = 0.95
        world = [(2.0, -1.0, 0.5)]

        env_map = _build_envelope_map(assignments, bone_map)
        stored = dict(env_map['envelopes'][0])
        # Renormalised 0.475/0.95 = 0.5
        assert stored == {'A': 0.5, 'B': 0.5}

        bind = _undeform_vertices(world, env_map, bones, bone_map, 0, None)
        redeformed = _deform_with(env_map['envelopes'], env_map['vertex_to_env'],
                                  bones, bone_map, bind)

        assert abs(redeformed[0][0] - world[0][0]) < 1e-4
        assert abs(redeformed[0][1] - world[0][1]) < 1e-4
        assert abs(redeformed[0][2] - world[0][2]) < 1e-4


# ---------------------------------------------------------------------------
# _find_skeleton_bone must mirror importer's flag search — otherwise compose
# un-deform and importer re-deform compute different coord matrices and rest
# vertices drift. Compose must walk up to the nearest bone carrying either
# SKELETON or SKELETON_ROOT; searching for SKELETON_ROOT only skips past
# closer SKELETON bones and lands on a different coord than the importer.
# ---------------------------------------------------------------------------

class TestFindSkeletonBone:
    def _bones_chain(self, flags_list, names=None):
        names = names or [f'B{i}' for i in range(len(flags_list))]
        bones = []
        for i, (name, f) in enumerate(zip(names, flags_list)):
            b = _FakeBone(name, _identity_4x4(), _identity_4x4(),
                          parent_index=(i - 1 if i > 0 else None))
            b.flags = f
            bones.append(b)
        return bones

    def test_finds_skeleton_root(self):
        bones = self._bones_chain([JOBJ_SKELETON_ROOT, 0, 0])
        assert _find_skeleton_bone(2, bones) == 0

    def test_finds_nearest_skeleton_bone_before_root(self):
        # Leaf -> SKELETON midpoint -> SKELETON_ROOT. Match must stop at
        # the midpoint, not walk all the way to the root. Compose using
        # only SKELETON_ROOT would land on bone 0 and compute a different
        # coord than the importer.
        bones = self._bones_chain([JOBJ_SKELETON_ROOT, JOBJ_SKELETON, 0])
        assert _find_skeleton_bone(2, bones) == 1

    def test_returns_self_when_self_has_skeleton(self):
        bones = self._bones_chain([JOBJ_SKELETON_ROOT, JOBJ_SKELETON])
        assert _find_skeleton_bone(1, bones) == 1

    def test_returns_none_when_no_skeleton_in_chain(self):
        bones = self._bones_chain([0, 0, 0])
        assert _find_skeleton_bone(2, bones) is None
