"""Regression: the exporter rejects unbaked armature/mesh transforms.

`_validate_baked_transforms` is the first thing `describe_blender_scene`
runs. It guarantees every armature and child mesh has identity
matrix_world before any decompose/recompose path runs on the bones. A
non-uniform scale combined with rotation on the armature produces a
sheared root world matrix; SRT decomposition of that matrix drops the
shear while direct vertex matmul keeps it, so the bone and vertex
transform paths disagree by exactly that shear, scaled by each bone's
distance from the root.

Pre-baking via the prep script eliminates the asymmetry at its source.
This test pins the rejection at the validation boundary so a future
regression in the prep script (or a user who skips it) gets a loud,
specific error instead of silently garbled output.
"""
import math

import pytest

pytest.importorskip("mathutils")

from mathutils import Matrix

from exporter.phases.describe.helpers.scene import (
    check_baked_transforms as _check_baked_transforms,
    _is_identity_matrix,
)
from exporter.phases.pre_process.pre_process import (
    MAX_TEXTURE_DIM,
    MAX_VERTEX_WEIGHTS,
    _check_texture_sizes,
    _check_vertex_weight_count,
    _check_baked_transforms as _preprocess_check_baked_transforms,
)


class _MockObj:
    """Minimal stand-in for a bpy.types.Object — only the attributes the
    validator reads."""
    def __init__(self, name, matrix_world):
        self.name = name
        self.matrix_world = matrix_world


class TestCheckBakedTransforms:
    def test_identity_armature_passes(self):
        arm = _MockObj('Armature', Matrix.Identity(4))
        _check_baked_transforms([arm], {arm: []})

    def test_rotated_armature_rejected(self):
        arm = _MockObj('Armature', Matrix.Rotation(math.pi / 4, 4, 'Z'))
        with pytest.raises(ValueError, match="Unbaked transforms.*Armature"):
            _check_baked_transforms([arm], {arm: []})

    def test_scaled_armature_rejected(self):
        arm = _MockObj('Armature', Matrix.Diagonal((2.0, 1.0, 1.0, 1.0)))
        with pytest.raises(ValueError, match="Unbaked transforms.*Armature"):
            _check_baked_transforms([arm], {arm: []})

    def test_translated_armature_rejected(self):
        arm = _MockObj('Armature', Matrix.Translation((1.0, 2.0, 3.0)))
        with pytest.raises(ValueError, match="Unbaked transforms.*Armature"):
            _check_baked_transforms([arm], {arm: []})

    def test_child_mesh_with_unbaked_transform_rejected(self):
        arm = _MockObj('Armature', Matrix.Identity(4))
        mesh = _MockObj('Body', Matrix.Diagonal((1.5, 1.5, 1.5, 1.0)))
        with pytest.raises(ValueError, match="Unbaked transforms.*Body"):
            _check_baked_transforms([arm], {arm: [mesh]})

    def test_clean_armature_with_clean_children_passes(self):
        arm = _MockObj('Armature', Matrix.Identity(4))
        mesh1 = _MockObj('Body', Matrix.Identity(4))
        mesh2 = _MockObj('Hair', Matrix.Identity(4))
        _check_baked_transforms([arm], {arm: [mesh1, mesh2]})

    def test_multiple_armatures_collects_all_offenders(self):
        arm1 = _MockObj('Arm1', Matrix.Diagonal((2.0, 2.0, 2.0, 1.0)))
        arm2 = _MockObj('Arm2', Matrix.Translation((1, 0, 0)))
        with pytest.raises(ValueError) as excinfo:
            _check_baked_transforms([arm1, arm2], {arm1: [], arm2: []})
        msg = str(excinfo.value)
        assert 'Arm1' in msg and 'Arm2' in msg

    def test_helpful_error_mentions_prep_script(self):
        arm = _MockObj('Armature', Matrix.Diagonal((2.0, 2.0, 2.0, 1.0)))
        with pytest.raises(ValueError, match="prepare_for_export"):
            _check_baked_transforms([arm], {arm: []})


class TestPreProcessBakedTransforms:
    """The pre-process check fires before the pipeline starts. Same condition
    as the describe-side check, but a clearer multi-line error message:
    counts armatures vs meshes separately, samples a few names, and shows
    both remediation paths (prep script + manual Apply All Transforms)."""

    def test_clean_scene_passes(self):
        arm = _MockObj('Armature', Matrix.Identity(4))
        mesh = _MockObj('Body', Matrix.Identity(4))
        _preprocess_check_baked_transforms([arm], {arm: [mesh]})

    def test_error_separates_armature_and_mesh_counts(self):
        arm = _MockObj('rig', Matrix.Diagonal((2.0, 2.0, 2.0, 1.0)))
        meshes = [_MockObj('m_%03d' % i, Matrix.Translation((i + 1, 0, 0)))
                  for i in range(20)]
        with pytest.raises(ValueError) as excinfo:
            _preprocess_check_baked_transforms([arm], {arm: meshes})
        msg = str(excinfo.value)
        assert "1 armature(s)" in msg
        assert "20 mesh(es)" in msg
        assert "rig" in msg
        # Only first 3 mesh names sampled — the user shouldn't get a wall of names.
        assert "m_000" in msg and "m_002" in msg
        assert "m_010" not in msg

    def test_error_lists_remediation_paths(self):
        arm = _MockObj('rig', Matrix.Diagonal((2.0, 1.0, 1.0, 1.0)))
        with pytest.raises(ValueError) as excinfo:
            _preprocess_check_baked_transforms([arm], {arm: []})
        msg = str(excinfo.value)
        assert "prepare_for_export.py" in msg
        assert "Apply > All Transforms" in msg

    def test_only_meshes_unbaked(self):
        arm = _MockObj('rig', Matrix.Identity(4))
        meshes = [_MockObj('a', Matrix.Translation((1, 0, 0)))]
        with pytest.raises(ValueError) as excinfo:
            _preprocess_check_baked_transforms([arm], {arm: meshes})
        msg = str(excinfo.value)
        assert "armature" not in msg.lower() or "mesh" in msg.lower()
        assert "1 mesh(es)" in msg


class _MockVertexGroup:
    def __init__(self, weight):
        self.weight = weight


class _MockVertex:
    def __init__(self, index, weights):
        self.index = index
        self.groups = [_MockVertexGroup(w) for w in weights]


class _MockMeshData:
    def __init__(self, vertices):
        self.vertices = vertices


class _MockMesh:
    def __init__(self, name, vertex_weights):
        self.name = name
        self.data = _MockMeshData([
            _MockVertex(i, ws) for i, ws in enumerate(vertex_weights)
        ])


class TestCheckVertexWeightCount:
    def test_four_weights_ok(self):
        mesh = _MockMesh('Body', [[0.25, 0.25, 0.25, 0.25]])
        _check_vertex_weight_count({object(): [mesh]})

    def test_five_weights_rejected(self):
        mesh = _MockMesh('Body', [[0.2, 0.2, 0.2, 0.2, 0.2]])
        with pytest.raises(ValueError, match="envelope limit of 4"):
            _check_vertex_weight_count({object(): [mesh]})

    def test_zero_weights_do_not_count(self):
        # A vertex group with weight 0 is inert; it should not count toward
        # the 4-influence cap.
        mesh = _MockMesh('Body', [[0.5, 0.5, 0.0, 0.0, 0.0]])
        _check_vertex_weight_count({object(): [mesh]})

    def test_error_mentions_prepare_script(self):
        mesh = _MockMesh('Body', [[0.2, 0.2, 0.2, 0.2, 0.2]])
        with pytest.raises(ValueError, match="prepare_for_export"):
            _check_vertex_weight_count({object(): [mesh]})

    def test_sample_offender_in_error(self):
        mesh = _MockMesh('Body', [[0.5, 0.5], [0.2, 0.2, 0.2, 0.2, 0.2]])
        with pytest.raises(ValueError, match=r"Body\[v1\]=5"):
            _check_vertex_weight_count({object(): [mesh]})

    def test_empty_mesh_list_ok(self):
        _check_vertex_weight_count({object(): []})

    def test_constant_matches_envelope_hardware_limit(self):
        assert MAX_VERTEX_WEIGHTS == 4


class TestCheckTextureSizes:
    def test_at_cap_ok(self):
        _check_texture_sizes([('Body.png', 512, 512)])

    def test_under_cap_ok(self):
        _check_texture_sizes([('Eye.png', 128, 64), ('Body.png', 256, 256)])

    def test_over_cap_width_rejected(self):
        with pytest.raises(ValueError, match="exceed GameCube cap"):
            _check_texture_sizes([('Body.png', 1024, 512)])

    def test_over_cap_height_rejected(self):
        with pytest.raises(ValueError, match="exceed GameCube cap"):
            _check_texture_sizes([('Body.png', 512, 1024)])

    def test_error_mentions_prepare_script(self):
        with pytest.raises(ValueError, match="prepare_for_export"):
            _check_texture_sizes([('Body.png', 2048, 2048)])

    def test_sample_offender_in_error(self):
        with pytest.raises(ValueError, match=r"Hair\.png \(1024x1024\)"):
            _check_texture_sizes([
                ('Body.png', 256, 256),
                ('Hair.png', 1024, 1024),
            ])

    def test_empty_list_ok(self):
        _check_texture_sizes([])

    def test_constant_matches_documented_cap(self):
        assert MAX_TEXTURE_DIM == 512


class TestIsIdentityMatrix:
    def test_exact_identity(self):
        assert _is_identity_matrix(Matrix.Identity(4))

    def test_within_tolerance(self):
        m = Matrix.Identity(4).copy()
        m[0][3] = 1e-7  # well below the 1e-5 tolerance
        assert _is_identity_matrix(m)

    def test_just_outside_tolerance(self):
        m = Matrix.Identity(4).copy()
        m[0][3] = 1e-3
        assert not _is_identity_matrix(m)

    def test_uniform_scale_not_identity(self):
        assert not _is_identity_matrix(Matrix.Diagonal((2.0, 2.0, 2.0, 1.0)))
