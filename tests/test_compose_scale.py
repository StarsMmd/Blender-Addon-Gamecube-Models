"""Tests for scale_scene_to_gc_units — the one-shot meters→GC pre-pass.

Two kinds of coverage:
  - Every length-bearing IR field is actually scaled (regression guard for
    when a new position field gets added but forgotten by the pre-pass).
  - Angles, weights, colors, and other dimensionless fields are *not*
    scaled.
"""
from shared.IR import IRScene
from shared.IR.skeleton import IRBone, IRModel
from shared.IR.geometry import IRMesh, IRBoneWeights
from shared.IR.material import IRImage
from shared.IR.animation import (
    IRKeyframe, IRBoneTrack, IRBoneAnimationSet, IRSplinePath,
)
from shared.IR.camera import IRCamera, IRCameraKeyframes
from shared.IR.lights import IRLight
from shared.IR.constraints import (
    IRLimitConstraint, IRIKConstraint, IRBoneReposition,
    IRCopyLocationConstraint, IRCopyRotationConstraint,
)
from shared.IR.enums import (
    ScaleInheritance, SkinType, Interpolation,
    CameraProjection, LightType,
)
from shared.helpers.scale import METERS_TO_GC
from exporter.phases.compose.helpers.scale import scale_scene_to_gc_units


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _matrix_with_translation(tx, ty, tz):
    return [[1, 0, 0, tx], [0, 1, 0, ty], [0, 0, 1, tz], [0, 0, 0, 1]]


def _kf(value, *, with_handles=False, with_slopes=False):
    return IRKeyframe(
        frame=0.0, value=value, interpolation=Interpolation.LINEAR,
        handle_left=(0.0, value) if with_handles else None,
        handle_right=(0.0, value) if with_handles else None,
        slope_in=value if with_slopes else None,
        slope_out=value if with_slopes else None,
    )


def _build_bone(name):
    return IRBone(
        name=name, parent_index=None,
        position=(1.0, 1.0, 1.0),
        rotation=(1.0, 1.0, 1.0),   # radians — must NOT scale
        scale=(1.0, 1.0, 1.0),      # dimensionless — must NOT scale
        inverse_bind_matrix=_matrix_with_translation(1.0, 1.0, 1.0),
        flags=0, is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED, ik_shrink=False,
        world_matrix=_matrix_with_translation(1.0, 1.0, 1.0),
        local_matrix=_matrix_with_translation(1.0, 1.0, 1.0),
        normalized_world_matrix=_matrix_with_translation(1.0, 1.0, 1.0),
        normalized_local_matrix=_matrix_with_translation(1.0, 1.0, 1.0),
        scale_correction=[[2, 0, 0, 0], [0, 2, 0, 0], [0, 0, 2, 0], [0, 0, 0, 1]],
        accumulated_scale=(1.0, 1.0, 1.0),
    )


def _build_mesh():
    return IRMesh(
        name='m', vertices=[(1.0, 1.0, 1.0), (2.0, 2.0, 2.0)],
        faces=[], uv_layers=[], color_layers=[], normals=None,
        material=None,
        bone_weights=IRBoneWeights(type=SkinType.WEIGHTED,
                                   assignments=[(0, [('b', 1.0)])]),
        is_hidden=False, parent_bone_index=0, cull_back=False,
        local_matrix=_matrix_with_translation(1.0, 1.0, 1.0),
    )


def _build_track():
    return IRBoneTrack(
        bone_name='b', bone_index=0,
        rotation=[[_kf(1.0)], [_kf(1.0)], [_kf(1.0)]],  # radians — not scaled
        location=[[_kf(1.0, with_handles=True, with_slopes=True)]] * 3,
        scale=[[_kf(1.0)], [_kf(1.0)], [_kf(1.0)]],     # dimensionless
        rest_local_matrix=_matrix_with_translation(1.0, 1.0, 1.0),
        rest_position=(1.0, 1.0, 1.0),
        spline_path=IRSplinePath(
            control_points=[[1.0, 1.0, 1.0], [2.0, 2.0, 2.0]],
            parameter_keyframes=[_kf(0.5)],  # curve parameter — not scaled
            world_matrix=_matrix_with_translation(1.0, 1.0, 1.0),
        ),
    )


def _build_scene():
    bone = _build_bone('b')
    mesh = _build_mesh()
    track = _build_track()
    anim_set = IRBoneAnimationSet(name='a', tracks=[track], loop=True)
    model = IRModel(name='m', bones=[bone], meshes=[mesh],
                    bone_animations=[anim_set])
    # Position-limit + IK constraints (location-bearing)
    model.limit_location_constraints.append(IRLimitConstraint(
        bone_name='b',
        min_x=-1.0, max_x=1.0, min_y=-1.0, max_y=1.0, min_z=-1.0, max_z=1.0,
    ))
    model.ik_constraints.append(IRIKConstraint(
        bone_name='b', chain_length=2, pole_angle=1.0,
        bone_repositions=[IRBoneReposition(bone_name='b', bone_length=1.0)],
    ))
    # Rotation-limit + non-position constraints — must NOT be touched.
    model.limit_rotation_constraints.append(IRLimitConstraint(
        bone_name='b', min_x=1.0, max_x=1.0,
    ))
    model.copy_location_constraints.append(IRCopyLocationConstraint(
        bone_name='b', target_bone='b', influence=1.0,
    ))
    model.copy_rotation_constraints.append(IRCopyRotationConstraint(
        bone_name='b', target_bone='b',
    ))

    camera = IRCamera(
        name='c', projection=CameraProjection.PERSPECTIVE,
        position=(1.0, 1.0, 1.0), target_position=(1.0, 1.0, 1.0),
        roll=1.0,                # radians — not scaled
        near=1.0, far=1.0,
        field_of_view=1.0,       # degrees — not scaled
        aspect=1.0,              # ratio — not scaled
        animations=[IRCameraKeyframes(
            name='c_a',
            eye_x=[_kf(1.0)], eye_y=[_kf(1.0)], eye_z=[_kf(1.0)],
            target_x=[_kf(1.0)], target_y=[_kf(1.0)], target_z=[_kf(1.0)],
            roll=[_kf(1.0)],  # radians — not scaled
            fov=[_kf(1.0)],   # degrees — not scaled
            near=[_kf(1.0)], far=[_kf(1.0)],
        )],
    )
    light = IRLight(name='l', type=LightType.POINT,
                    color=(1.0, 1.0, 1.0),
                    position=(1.0, 1.0, 1.0),
                    target_position=(1.0, 1.0, 1.0))

    scene = IRScene(models=[model], cameras=[camera], lights=[light])
    return scene


# ---------------------------------------------------------------------------
# Length fields scaled
# ---------------------------------------------------------------------------

class TestScaleScene:
    def test_bone_position_scaled(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        assert scene.models[0].bones[0].position == (
            METERS_TO_GC, METERS_TO_GC, METERS_TO_GC)

    def test_bone_all_matrices_translation_scaled(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        b = scene.models[0].bones[0]
        for m in (b.world_matrix, b.local_matrix,
                  b.normalized_world_matrix, b.normalized_local_matrix,
                  b.inverse_bind_matrix):
            assert m[0][3] == METERS_TO_GC
            assert m[1][3] == METERS_TO_GC
            assert m[2][3] == METERS_TO_GC

    def test_mesh_vertices_and_local_matrix_scaled(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        mesh = scene.models[0].meshes[0]
        assert mesh.vertices[0] == (METERS_TO_GC, METERS_TO_GC, METERS_TO_GC)
        assert mesh.vertices[1] == (2 * METERS_TO_GC,) * 3
        assert mesh.local_matrix[0][3] == METERS_TO_GC

    def test_location_keyframes_scaled_with_handles_and_slopes(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        track = scene.models[0].bone_animations[0].tracks[0]
        for axis in range(3):
            kf = track.location[axis][0]
            assert kf.value == METERS_TO_GC
            assert kf.handle_left[1] == METERS_TO_GC
            assert kf.handle_right[1] == METERS_TO_GC
            assert kf.slope_in == METERS_TO_GC
            assert kf.slope_out == METERS_TO_GC

    def test_rest_position_and_rest_local_matrix_scaled(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        track = scene.models[0].bone_animations[0].tracks[0]
        assert track.rest_position == (METERS_TO_GC,) * 3
        assert track.rest_local_matrix[0][3] == METERS_TO_GC

    def test_spline_path_scaled(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        sp = scene.models[0].bone_animations[0].tracks[0].spline_path
        assert sp.control_points == [[METERS_TO_GC] * 3, [2 * METERS_TO_GC] * 3]
        assert sp.world_matrix[0][3] == METERS_TO_GC

    def test_camera_position_target_near_far_scaled(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        cam = scene.cameras[0]
        assert cam.position == (METERS_TO_GC,) * 3
        assert cam.target_position == (METERS_TO_GC,) * 3
        assert cam.near == METERS_TO_GC
        assert cam.far == METERS_TO_GC

    def test_camera_position_keyframes_scaled(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        anim = scene.cameras[0].animations[0]
        for attr in ('eye_x', 'eye_y', 'eye_z',
                     'target_x', 'target_y', 'target_z',
                     'near', 'far'):
            assert getattr(anim, attr)[0].value == METERS_TO_GC

    def test_light_position_scaled(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        light = scene.lights[0]
        assert light.position == (METERS_TO_GC,) * 3
        assert light.target_position == (METERS_TO_GC,) * 3

    def test_limit_location_bounds_scaled(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        c = scene.models[0].limit_location_constraints[0]
        assert c.min_x == -METERS_TO_GC
        assert c.max_x == METERS_TO_GC
        assert c.min_y == -METERS_TO_GC
        assert c.max_y == METERS_TO_GC

    def test_ik_bone_length_scaled(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        ik = scene.models[0].ik_constraints[0]
        assert ik.bone_repositions[0].bone_length == METERS_TO_GC


# ---------------------------------------------------------------------------
# Non-length fields untouched
# ---------------------------------------------------------------------------

class TestAnglesAndWeightsUntouched:
    def test_bone_rotation_scale_and_scale_correction_untouched(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        b = scene.models[0].bones[0]
        assert b.rotation == (1.0, 1.0, 1.0)   # radians
        assert b.scale == (1.0, 1.0, 1.0)      # dimensionless
        # scale_correction is pure scale/rotation — translation column was 0
        assert b.scale_correction[0][3] == 0
        assert b.scale_correction[0][0] == 2

    def test_rotation_and_scale_keyframes_untouched(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        track = scene.models[0].bone_animations[0].tracks[0]
        for axis in range(3):
            assert track.rotation[axis][0].value == 1.0
            assert track.scale[axis][0].value == 1.0

    def test_mesh_bone_weights_untouched(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        bw = scene.models[0].meshes[0].bone_weights
        assert bw.assignments[0][1][0][1] == 1.0   # vertex weight

    def test_camera_fov_roll_aspect_untouched(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        cam = scene.cameras[0]
        assert cam.roll == 1.0
        assert cam.field_of_view == 1.0
        assert cam.aspect == 1.0

    def test_camera_fov_and_roll_keyframes_untouched(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        anim = scene.cameras[0].animations[0]
        assert anim.fov[0].value == 1.0
        assert anim.roll[0].value == 1.0

    def test_spline_parameter_keyframes_untouched(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        sp = scene.models[0].bone_animations[0].tracks[0].spline_path
        assert sp.parameter_keyframes[0].value == 0.5

    def test_limit_rotation_bounds_untouched(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        c = scene.models[0].limit_rotation_constraints[0]
        assert c.min_x == 1.0   # radians

    def test_copy_location_constraint_influence_untouched(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        c = scene.models[0].copy_location_constraints[0]
        assert c.influence == 1.0

    def test_ik_pole_angle_untouched(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        assert scene.models[0].ik_constraints[0].pole_angle == 1.0


# ---------------------------------------------------------------------------
# Round-trip: scaling by METERS_TO_GC then its reciprocal is identity.
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_scale_then_inverse_returns_original(self):
        scene = _build_scene()
        scale_scene_to_gc_units(scene)
        scale_scene_to_gc_units(scene, factor=1.0 / METERS_TO_GC)
        b = scene.models[0].bones[0]
        assert abs(b.position[0] - 1.0) < 1e-9
        assert abs(b.world_matrix[0][3] - 1.0) < 1e-9
        assert abs(scene.models[0].meshes[0].vertices[0][0] - 1.0) < 1e-9
        assert abs(scene.cameras[0].near - 1.0) < 1e-9
