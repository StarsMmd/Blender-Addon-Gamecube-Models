"""Tests for envelope deformation in describe phase — vertex and normal transforms."""
import math
from types import SimpleNamespace

from shared.helpers.math_shim import Matrix, Vector
from shared.Constants.hsd import (
    JOBJ_SKELETON_ROOT, JOBJ_SKELETON, POBJ_ENVELOPE,
)
from shared.Constants.gx import GX_VA_PNMTXIDX, GX_VA_POS
from shared.IR.enums import SkinType
from importer.phases.describe.helpers.meshes import (
    _extract_envelope_weights, _envelope_coord_system, _get_invbind_matrix,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_bone(name='bone', flags=0, world_matrix=None, inverse_bind_matrix=None,
               parent_index=None):
    if world_matrix is None:
        world_matrix = Matrix.Identity(4).transposed()  # row-major list
    if isinstance(world_matrix, Matrix):
        world_matrix = [list(row) for row in world_matrix]
    return SimpleNamespace(
        name=name,
        flags=flags,
        world_matrix=world_matrix,
        inverse_bind_matrix=inverse_bind_matrix,
        parent_index=parent_index,
        mesh_indices=[],
    )


def _make_envelope_entry(weight, joint_address):
    joint = SimpleNamespace(address=joint_address)
    return SimpleNamespace(weight=weight, joint=joint)


def _make_envelope(entries):
    """entries: list of (weight, joint_address)."""
    return SimpleNamespace(
        envelopes=[_make_envelope_entry(w, addr) for w, addr in entries],
    )


def _make_pobj(envelope_list, env_source, env_faces, pos_faces):
    """Build a minimal PObject mock for envelope testing.

    env_source: list of raw envelope index values (multiplied by 3 internally).
    env_faces: face list for envelope index attribute.
    pos_faces: face list for position attribute (also used as main faces).
    """
    vtx_pnmtx = SimpleNamespace(attribute=GX_VA_PNMTXIDX)
    vtx_pos = SimpleNamespace(attribute=GX_VA_POS)
    vertex_list = SimpleNamespace(vertices=[vtx_pnmtx, vtx_pos])

    return SimpleNamespace(
        vertex_list=vertex_list,
        property=envelope_list,
        flags=POBJ_ENVELOPE,
        sources={0: env_source, 1: []},
        face_lists={0: env_faces, 1: pos_faces},
    )


# ---------------------------------------------------------------------------
# Normal matrix math
# ---------------------------------------------------------------------------

class TestNormalMatrixMath:
    """Verify that inverse-transpose correctly transforms normals."""

    def test_identity_matrix_preserves_normals(self):
        """Identity deform matrix should leave normals unchanged."""
        dm = Matrix.Identity(4)
        nm = dm.to_3x3()
        nm.invert()
        nm.transpose()
        n = Vector((0, 1, 0))
        result = (nm.to_4x4() @ n).normalized()
        assert abs(result.x) < 1e-6
        assert abs(result.y - 1.0) < 1e-6
        assert abs(result.z) < 1e-6

    def test_uniform_scale_preserves_normal_direction(self):
        """Uniform scaling should preserve normal direction after normalization."""
        dm = Matrix.Identity(4)
        dm[0][0] = 2.0
        dm[1][1] = 2.0
        dm[2][2] = 2.0
        nm = dm.to_3x3()
        nm.invert()
        nm.transpose()
        n = Vector((0, 0, 1))
        result = (nm.to_4x4() @ n).normalized()
        assert abs(result.x) < 1e-6
        assert abs(result.y) < 1e-6
        assert abs(result.z - 1.0) < 1e-6

    def test_non_uniform_scale_adjusts_normal(self):
        """Non-uniform scaling should tilt normals away from the stretched axis."""
        dm = Matrix.Identity(4)
        dm[0][0] = 2.0  # stretch X
        # A diagonal (1,1,0) normal on a surface stretched in X
        # should tilt toward Y (away from the stretch)
        nm = dm.to_3x3()
        nm.invert()
        nm.transpose()
        n = Vector((1, 1, 0)).normalized()
        result = (nm.to_4x4() @ n).normalized()
        # After inverse-transpose of scale(2,1,1), the X component should be halved
        # relative to Y, so the result tilts toward Y
        assert result.y > result.x

    def test_rotation_rotates_normal(self):
        """Pure rotation should rotate the normal the same way."""
        angle = math.pi / 2  # 90 degrees around Z
        dm = Matrix.Rotation(angle, 4, 'Z')
        nm = dm.to_3x3()
        nm.invert()
        nm.transpose()
        n = Vector((1, 0, 0))
        result = (nm.to_4x4() @ n).normalized()
        # (1,0,0) rotated 90° around Z → (0,1,0)
        assert abs(result.x) < 1e-6
        assert abs(result.y - 1.0) < 1e-6
        assert abs(result.z) < 1e-6

    def test_translation_does_not_affect_normal(self):
        """Translation should not affect normals (they're directions, not positions)."""
        dm = Matrix.Identity(4)
        dm[0][3] = 100.0
        dm[1][3] = 200.0
        dm[2][3] = 300.0
        nm = dm.to_3x3()  # 3x3 strips translation
        nm.invert()
        nm.transpose()
        n = Vector((0, 1, 0))
        result = (nm.to_4x4() @ n).normalized()
        assert abs(result.x) < 1e-6
        assert abs(result.y - 1.0) < 1e-6
        assert abs(result.z) < 1e-6


# ---------------------------------------------------------------------------
# Envelope integration tests
# ---------------------------------------------------------------------------

class TestExtractEnvelopeNormals:
    """Test that _extract_envelope_weights transforms normals alongside vertices."""

    def _run_envelope(self, world_matrix, vertices, normals, faces,
                      inv_bind=None):
        """Run envelope extraction with a single bone, single envelope, identity coord."""
        bone = _make_bone(
            name='root',
            flags=JOBJ_SKELETON_ROOT,
            world_matrix=world_matrix,
            inverse_bind_matrix=inv_bind,
        )
        bones = [bone]
        jtb = {100: 0}  # joint address 100 → bone index 0

        envelope = _make_envelope([(1.0, 100)])  # single bone, weight=1

        # Each vertex maps to envelope 0 (env_source values are multiplied by 3)
        n_verts = len(vertices)
        env_source = [0] * n_verts  # all map to envelope 0 (0 // 3 = 0)
        env_faces = list(faces)
        pos_faces = list(faces)

        pobj = _make_pobj([envelope], env_source, env_faces, pos_faces)

        verts_out = list(vertices)
        normals_out = list(normals) if normals else None

        result = _extract_envelope_weights(
            pobj, None, 0, bones, jtb, faces,
            verts_out, normals_out,
        )

        return verts_out, normals_out, result

    def test_identity_leaves_normals_unchanged(self):
        """Identity world matrix should not modify normals."""
        verts = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
        normals = [(0, 0, 1), (0, 0, 1), (0, 0, 1)]
        faces = [[0, 1, 2]]

        _, normals_out, bw = self._run_envelope(
            Matrix.Identity(4), verts, normals, faces,
        )

        assert bw.type == SkinType.WEIGHTED
        for n in normals_out:
            assert abs(n[0]) < 1e-6
            assert abs(n[1]) < 1e-6
            assert abs(n[2] - 1.0) < 1e-6

    def test_rotation_transforms_normals(self):
        """90° rotation around Z should rotate normals."""
        angle = math.pi / 2
        world = Matrix.Rotation(angle, 4, 'Z')

        verts = [(1, 0, 0)]
        normals = [(1, 0, 0)]  # normal pointing +X
        faces = [[0]]

        _, normals_out, _ = self._run_envelope(world, verts, normals, faces)

        # Normal (1,0,0) rotated 90° around Z → (0,1,0)
        assert abs(normals_out[0][0]) < 1e-5
        assert abs(normals_out[0][1] - 1.0) < 1e-5
        assert abs(normals_out[0][2]) < 1e-5

    def test_vertices_and_normals_both_transformed(self):
        """Both vertices and normals should be transformed by the deform matrix."""
        # Translation + rotation
        angle = math.pi / 2
        world = Matrix.Rotation(angle, 4, 'Z')
        world[0][3] = 10.0  # translate X by 10

        verts = [(1, 0, 0)]
        normals = [(1, 0, 0)]
        faces = [[0]]

        verts_out, normals_out, _ = self._run_envelope(
            world, verts, normals, faces,
        )

        # Vertex: rotated (1,0,0) → (0,1,0), then translated → (10,1,0)
        assert abs(verts_out[0][0] - 10.0) < 1e-5
        assert abs(verts_out[0][1] - 1.0) < 1e-5

        # Normal: rotation only (translation doesn't affect normals)
        assert abs(normals_out[0][0]) < 1e-5
        assert abs(normals_out[0][1] - 1.0) < 1e-5

    def test_normals_normalized_after_transform(self):
        """Normals should be unit length after transformation."""
        world = Matrix.Identity(4)
        world[0][0] = 3.0  # non-uniform scale

        verts = [(1, 0, 0)]
        normals = [(1, 1, 0)]  # not unit length input, but normalize in extract
        faces = [[0]]

        _, normals_out, _ = self._run_envelope(world, verts, normals, faces)

        length = sum(c * c for c in normals_out[0]) ** 0.5
        assert abs(length - 1.0) < 1e-5

    def test_no_normals_does_not_crash(self):
        """Passing normals=None should not error."""
        verts = [(1, 0, 0)]
        faces = [[0]]

        verts_out, normals_out, _ = self._run_envelope(
            Matrix.Identity(4), verts, None, faces,
        )

        assert normals_out is None
        # Vertices should still be deformed
        assert len(verts_out) == 1

    def test_multiple_faces_all_normals_transformed(self):
        """All per-loop normals across multiple faces should be transformed."""
        angle = math.pi / 2
        world = Matrix.Rotation(angle, 4, 'Z')

        verts = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0)]
        # 6 loops: 2 faces × 3 verts
        normals = [
            (1, 0, 0), (0, 1, 0), (0, 0, 1),  # face 0
            (1, 0, 0), (0, 0, 1), (0, 1, 0),  # face 1
        ]
        faces = [[0, 1, 2], [0, 2, 3]]

        _, normals_out, _ = self._run_envelope(world, verts, normals, faces)

        assert len(normals_out) == 6
        # All normals should have been transformed (no zero-length artifacts)
        for n in normals_out:
            length = sum(c * c for c in n) ** 0.5
            assert abs(length - 1.0) < 1e-5

    def test_multi_envelope_different_matrices(self):
        """Different vertices can have different envelope matrices."""
        bone_a = _make_bone(
            name='bone_a', flags=JOBJ_SKELETON_ROOT,
            world_matrix=Matrix.Rotation(math.pi / 2, 4, 'Z'),
        )
        bone_b = _make_bone(
            name='bone_b', flags=0,
            world_matrix=Matrix.Rotation(-math.pi / 2, 4, 'Z'),
            parent_index=0,
        )
        bones = [bone_a, bone_b]
        jtb = {100: 0, 200: 1}

        env_0 = _make_envelope([(1.0, 100)])  # bone_a
        env_1 = _make_envelope([(1.0, 200)])  # bone_b

        # Vertex 0 → envelope 0, vertex 1 → envelope 1
        # env_source values are raw: envelope_idx = value // 3
        env_source = [0, 3]  # 0//3=0, 3//3=1
        faces = [[0, 1]]
        env_faces = [[0, 1]]

        pobj = _make_pobj([env_0, env_1], env_source, env_faces, faces)

        verts = [(1, 0, 0), (1, 0, 0)]
        normals = [(1, 0, 0), (1, 0, 0)]

        result_bw = _extract_envelope_weights(
            pobj, None, 0, bones, jtb, faces,
            verts, normals,
        )

        # Vertex 0 normal: rotated +90° → (0, 1, 0)
        assert abs(normals[0][0]) < 1e-5
        assert abs(normals[0][1] - 1.0) < 1e-5

        # Vertex 1 normal: rotated -90° → (0, -1, 0)
        assert abs(normals[1][0]) < 1e-5
        assert abs(normals[1][1] - (-1.0)) < 1e-5


class TestEnvelopeCoordSystem:

    def test_skeleton_root_returns_none(self):
        bone = _make_bone(flags=JOBJ_SKELETON_ROOT)
        assert _envelope_coord_system(0, [bone]) is None

    def test_no_skeleton_returns_none(self):
        bone = _make_bone(flags=0, parent_index=None)
        assert _envelope_coord_system(0, [bone]) is None


class TestGetInvbindMatrix:

    def test_no_invbind_returns_identity(self):
        bone = _make_bone(inverse_bind_matrix=None, parent_index=None)
        result = _get_invbind_matrix(0, [bone])
        for i in range(4):
            for j in range(4):
                expected = 1.0 if i == j else 0.0
                assert abs(result[i][j] - expected) < 1e-6

    def test_walks_parent_chain(self):
        invbind = [[2 if i == j else 0 for j in range(4)] for i in range(4)]
        parent = _make_bone(name='parent', inverse_bind_matrix=invbind, parent_index=None)
        child = _make_bone(name='child', inverse_bind_matrix=None, parent_index=0)
        result = _get_invbind_matrix(1, [parent, child])
        assert abs(result[0][0] - 2.0) < 1e-6
