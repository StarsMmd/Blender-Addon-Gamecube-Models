"""Tests for the export-side material animation readback helpers.

Focuses on the pieces that don't need a full Blender action: the
material_mesh_name lookup construction and the fcurve-keyframe parsing
via fakes.
"""
from shared.IR.skeleton import IRBone
from shared.IR.geometry import IRMesh
from shared.IR.enums import ScaleInheritance, Interpolation
from shared.IR.animation import IRKeyframe
from exporter.phases.describe_blender.helpers.material_animations import (
    build_material_lookup_from_meshes,
    _fcurve_to_keyframes,
    _build_material_track,
    _UV_FIELD_LOOKUP,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _identity():
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _make_bone(name, parent_index=None):
    return IRBone(
        name=name, parent_index=parent_index,
        position=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1),
        inverse_bind_matrix=None, flags=0, is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED, ik_shrink=False,
        world_matrix=_identity(), local_matrix=_identity(),
        normalized_world_matrix=_identity(),
        normalized_local_matrix=_identity(),
        scale_correction=_identity(),
        accumulated_scale=(1, 1, 1),
    )


def _make_mesh(name, parent_bone_index):
    return IRMesh(
        name=name, vertices=[(0, 0, 0)], faces=[],
        uv_layers=[], color_layers=[], normals=None,
        material=None, bone_weights=None, is_hidden=False,
        parent_bone_index=parent_bone_index, cull_back=False,
    )


class _FakeMat:
    """A stand-in for bpy.types.Material — only identity matters."""
    def __init__(self, name): self.name = name


class _FakeKP:
    def __init__(self, frame, value,
                 interp='LINEAR', hl=None, hr=None):
        self.co = (frame, value)
        self.interpolation = interp
        self.handle_left = hl or (frame - 1, value)
        self.handle_right = hr or (frame + 1, value)


class _FakeFCurve:
    def __init__(self, data_path, array_index, keyframe_points):
        self.data_path = data_path
        self.array_index = array_index
        self.keyframe_points = keyframe_points


class _FakeAction:
    def __init__(self, name, fcurves=()):
        self.name = name
        self.fcurves = list(fcurves)
        self.layers = []   # forces the flat-fcurve fallback path


# ---------------------------------------------------------------------------
# build_material_lookup_from_meshes
# ---------------------------------------------------------------------------

class TestBuildMaterialLookup:
    def test_first_mesh_per_material_wins(self):
        bones = [_make_bone("root"), _make_bone("arm", parent_index=0)]
        mat_a = _FakeMat("a")
        mat_b = _FakeMat("b")
        meshes = [
            _make_mesh("m0", parent_bone_index=0),  # mat_a
            _make_mesh("m1", parent_bone_index=1),  # mat_b
            _make_mesh("m2", parent_bone_index=0),  # mat_a again (same instance)
        ]
        mats = [mat_a, mat_b, mat_a]

        lookup = build_material_lookup_from_meshes(meshes, mats, bones)

        # Two-digit zero padding because the largest index is 2.
        assert lookup == {id(mat_a): "mesh_0_root", id(mat_b): "mesh_1_arm"}

    def test_none_materials_are_skipped(self):
        bones = [_make_bone("root")]
        mat = _FakeMat("a")
        meshes = [_make_mesh("m0", 0), _make_mesh("m1", 0)]
        lookup = build_material_lookup_from_meshes(meshes, [None, mat], bones)
        # The first mesh has no material, so mat is the only entry.
        # mesh_digits is 1 (max index is 1).
        assert lookup == {id(mat): "mesh_1_root"}

    def test_empty_inputs(self):
        assert build_material_lookup_from_meshes([], [], []) == {}
        assert build_material_lookup_from_meshes(None, None, []) == {}


# ---------------------------------------------------------------------------
# _fcurve_to_keyframes — interpolation mapping + sRGB reverse
# ---------------------------------------------------------------------------

class TestFCurveToKeyframes:
    def test_linear_alpha_passes_through(self):
        fc = _FakeFCurve('node_tree.nodes["AlphaValue"].outputs[0].default_value', 0, [
            _FakeKP(0.0, 0.25), _FakeKP(10.0, 0.75, 'CONSTANT'),
        ])
        kfs = _fcurve_to_keyframes(fc, linearize_from_blender=False)
        assert len(kfs) == 2
        assert kfs[0].value == 0.25
        assert kfs[0].interpolation == Interpolation.LINEAR
        assert kfs[1].value == 0.75
        assert kfs[1].interpolation == Interpolation.CONSTANT

    def test_diffuse_gets_reverse_srgb(self):
        # Blender stores scene-linear; IR stores sRGB. linear_to_srgb(0.5) ≈ 0.7354.
        fc = _FakeFCurve('node_tree.nodes["DiffuseColor"].outputs[0].default_value', 0, [
            _FakeKP(0.0, 0.5),
        ])
        kfs = _fcurve_to_keyframes(fc, linearize_from_blender=True)
        assert 0.73 < kfs[0].value < 0.74


# ---------------------------------------------------------------------------
# _build_material_track — end-to-end on a simulated action
# ---------------------------------------------------------------------------

class TestBuildMaterialTrack:
    def test_collects_all_four_channels(self):
        action = _FakeAction('Walk_Loop')
        fcurves = [
            _FakeFCurve('node_tree.nodes["DiffuseColor"].outputs[0].default_value',
                        0, [_FakeKP(0.0, 1.0)]),
            _FakeFCurve('node_tree.nodes["DiffuseColor"].outputs[0].default_value',
                        1, [_FakeKP(0.0, 0.0)]),
            _FakeFCurve('node_tree.nodes["DiffuseColor"].outputs[0].default_value',
                        2, [_FakeKP(0.0, 0.0)]),
            _FakeFCurve('node_tree.nodes["AlphaValue"].outputs[0].default_value',
                        0, [_FakeKP(0.0, 0.5)]),
        ]
        track = _build_material_track('mesh_0_Bone', fcurves, action, logger=None)
        assert track.material_mesh_name == 'mesh_0_Bone'
        assert track.diffuse_r is not None
        assert track.diffuse_g is not None
        assert track.diffuse_b is not None
        assert track.alpha is not None
        assert track.loop is True  # name contains '_Loop'

    def test_uv_fcurves_populate_uv_tracks_by_texture_index(self):
        action = _FakeAction('Run')
        fcurves = [
            # TexMapping_0 translation U
            _FakeFCurve('node_tree.nodes["TexMapping_0"].inputs[1].default_value',
                        0, [_FakeKP(0.0, 0.5)]),
            # TexMapping_0 scale V
            _FakeFCurve('node_tree.nodes["TexMapping_0"].inputs[3].default_value',
                        1, [_FakeKP(0.0, 2.0)]),
            # TexMapping_2 rotation Z
            _FakeFCurve('node_tree.nodes["TexMapping_2"].inputs[2].default_value',
                        2, [_FakeKP(0.0, 1.5)]),
        ]
        track = _build_material_track('mesh_0_Bone', fcurves, action, logger=None)
        # Sorted by texture_index → tex 0 first, then tex 2.
        assert len(track.texture_uv_tracks) == 2
        assert track.texture_uv_tracks[0].texture_index == 0
        assert track.texture_uv_tracks[0].translation_u is not None
        assert track.texture_uv_tracks[0].scale_v is not None
        assert track.texture_uv_tracks[1].texture_index == 2
        assert track.texture_uv_tracks[1].rotation_z is not None
        assert track.loop is False  # name does not contain '_Loop'

    def test_returns_none_when_no_material_fcurves(self):
        action = _FakeAction('Idle')
        # An unrelated fcurve (e.g. bone pose) shouldn't produce a track.
        fcurves = [
            _FakeFCurve('pose.bones["b"].rotation_euler', 0, [_FakeKP(0.0, 0.0)]),
        ]
        assert _build_material_track('mesh_0_b', fcurves, action, logger=None) is None


# ---------------------------------------------------------------------------
# UV field lookup — matches the importer's write side
# ---------------------------------------------------------------------------

class TestUVFieldLookup:
    def test_all_seven_uv_axes_mapped(self):
        # input 1 = translation (u, v), input 2 = rotation (x, y, z),
        # input 3 = scale (u, v) — same as importer UV_TRACK_MAP.
        expected = {
            (1, 0): 'translation_u',
            (1, 1): 'translation_v',
            (2, 0): 'rotation_x',
            (2, 1): 'rotation_y',
            (2, 2): 'rotation_z',
            (3, 0): 'scale_u',
            (3, 1): 'scale_v',
        }
        assert _UV_FIELD_LOOKUP == expected
