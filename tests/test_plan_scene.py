"""Unit tests for Plan-phase scene helpers (lights, cameras, constraints
pass-through, particle summary).
"""
import math
from types import SimpleNamespace

from shared.IR.enums import CameraProjection, Interpolation
from shared.IR.animation import IRKeyframe
from shared.BR.lights import BRLight
from shared.BR.cameras import BRCamera, BRCameraAnimation
from shared.BR.constraints import BRConstraints, BRParticleSummary
from importer.phases.plan.helpers.scene import (
    plan_light, plan_lights,
    plan_camera, plan_cameras,
    plan_constraints, plan_particle_summary,
    _fov_to_lens, _gc_to_blender,
)


def _stub_ir_light(name='L', type_value='POINT', color=(1.0, 1.0, 1.0),
                   brightness=10.0, position=(1.0, 2.0, 3.0),
                   target_position=None):
    light_type = SimpleNamespace(value=type_value)
    return SimpleNamespace(
        name=name,
        type=light_type,
        color=color,
        brightness=brightness,
        position=position,
        target_position=target_position,
    )


def _stub_ir_camera(name='C', projection=CameraProjection.PERSPECTIVE, field_of_view=45.0,
                    aspect=1.77, near=0.1, far=100.0, position=(0.0, 0.0, 5.0),
                    target_position=None, animations=None):
    return SimpleNamespace(
        name=name,
        projection=projection,
        field_of_view=field_of_view,
        aspect=aspect,
        near=near,
        far=far,
        position=position,
        target_position=target_position,
        animations=animations or [],
    )


class TestPlanLight:

    def test_point_light_basic_translation(self):
        ir = _stub_ir_light(type_value='POINT', brightness=15.0, position=(1.0, 2.0, 3.0))
        br = plan_light(ir)
        assert isinstance(br, BRLight)
        assert br.blender_type == 'POINT'
        assert br.energy == 15.0
        assert br.is_ambient is False

    def test_coord_gc_y_up_to_blender_z_up(self):
        """Blender expects (x, -z, y) for GC's (x, y, z)."""
        ir = _stub_ir_light(position=(1.0, 2.0, 3.0))
        br = plan_light(ir)
        assert br.location == (1.0, -3.0, 2.0)

    def test_ambient_light_zero_energy_flagged(self):
        ir = _stub_ir_light(type_value='AMBIENT', brightness=5.0, position=(0.0, 0.0, 0.0))
        br = plan_light(ir)
        assert br.is_ambient is True
        assert br.energy == 0.0
        # Ambient → POINT as far as bpy type, but flagged for build layer.
        assert br.blender_type == 'POINT'

    def test_srgb_color_linearized(self):
        """IR stores sRGB; BR holds linear values for direct bpy consumption."""
        ir = _stub_ir_light(color=(0.5, 0.5, 0.5))
        br = plan_light(ir)
        # srgb_to_linear(0.5) ≈ 0.2140
        assert all(abs(c - 0.2140) < 0.01 for c in br.color)

    def test_target_location_also_rotated(self):
        ir = _stub_ir_light(target_position=(4.0, 5.0, 6.0))
        br = plan_light(ir)
        assert br.target_location == (4.0, -6.0, 5.0)

    def test_no_target_position_stays_none(self):
        ir = _stub_ir_light(target_position=None)
        br = plan_light(ir)
        assert br.target_location is None


class TestFovToLens:

    def test_fov_45_matches_formula(self):
        lens = _fov_to_lens(45.0, 18.0)
        expected = 18.0 / (2.0 * math.tan(math.radians(45.0) / 2.0))
        assert abs(lens - expected) < 1e-9

    def test_fov_0_falls_back_to_default(self):
        assert _fov_to_lens(0.0, 18.0) == 50.0

    def test_fov_ge_180_falls_back_to_default(self):
        assert _fov_to_lens(180.0, 18.0) == 50.0
        assert _fov_to_lens(200.0, 18.0) == 50.0


class TestPlanCamera:

    def test_persp_camera_fov_converted_to_lens(self):
        ir = _stub_ir_camera(projection=CameraProjection.PERSPECTIVE, field_of_view=60.0)
        br = plan_camera(ir)
        assert br.projection == 'PERSP'
        # 18 / (2 * tan(30°)) ≈ 15.588
        assert abs(br.lens - 15.588) < 0.01

    def test_ortho_camera_lens_holds_ortho_scale(self):
        ir = _stub_ir_camera(projection=CameraProjection.ORTHO, field_of_view=5.0)
        br = plan_camera(ir)
        assert br.projection == 'ORTHO'
        # For ortho, FOV field is repurposed as ortho_scale.
        assert br.lens == 5.0

    def test_clip_planes_passed_through(self):
        ir = _stub_ir_camera(near=0.05, far=500.0)
        br = plan_camera(ir)
        assert br.clip_start == 0.05
        assert br.clip_end == 500.0

    def test_position_coord_rotated(self):
        ir = _stub_ir_camera(position=(1.0, 2.0, 3.0))
        br = plan_camera(ir)
        assert br.location == (1.0, -3.0, 2.0)


class TestPlanCameraAnimation:

    def test_eye_z_negated_when_converted_to_blender_y(self):
        """GC eye_z → Blender loc_y with sign flip."""
        anim = SimpleNamespace(
            name='cam_anim',
            eye_x=[IRKeyframe(frame=0, value=1.0, interpolation=Interpolation.LINEAR)],
            eye_y=[IRKeyframe(frame=0, value=2.0, interpolation=Interpolation.LINEAR)],
            eye_z=[IRKeyframe(frame=0, value=3.0, interpolation=Interpolation.LINEAR)],
            roll=[], fov=[], near=[], far=[],
            target_x=[], target_y=[], target_z=[],
            end_frame=10.0, loop=False,
        )
        ir = _stub_ir_camera(animations=[anim])
        br = plan_camera(ir)

        br_anim = br.animations[0]
        assert br_anim.loc_x[0].value == 1.0  # eye_x → loc_x
        assert br_anim.loc_y[0].value == -3.0  # eye_z → loc_y negated
        assert br_anim.loc_z[0].value == 2.0  # eye_y → loc_z

    def test_fov_keyframes_converted_to_lens(self):
        anim = SimpleNamespace(
            name='cam_anim',
            eye_x=[], eye_y=[], eye_z=[],
            roll=[], near=[], far=[],
            fov=[IRKeyframe(frame=0, value=60.0, interpolation=Interpolation.LINEAR)],
            target_x=[], target_y=[], target_z=[],
            end_frame=10.0, loop=False,
        )
        ir = _stub_ir_camera(animations=[anim])
        br = plan_camera(ir)
        # Same conversion as the single-value FOV.
        assert abs(br.animations[0].lens[0].value - 15.588) < 0.01


class TestPlanConstraints:

    def test_all_empty_gives_empty_bundle(self):
        br = plan_constraints([], [], [], [], [], [])
        assert isinstance(br, BRConstraints)
        assert br.is_empty
        assert br.total == 0

    def test_field_counts_summed(self):
        br = plan_constraints(['a'], ['b'], ['c', 'd'], [], ['e'], [])
        assert br.total == 5
        assert len(br.ik) == 1
        assert len(br.copy_location) == 1
        assert len(br.track_to) == 2
        assert len(br.limit_rotation) == 1


class TestPlanParticleSummary:

    def test_none_ir_returns_none(self):
        assert plan_particle_summary(None) is None

    def test_counts_from_ir_lists(self):
        ir_particles = SimpleNamespace(
            generators=[0, 1, 2],
            textures=['t1', 't2'],
        )
        br = plan_particle_summary(ir_particles)
        assert isinstance(br, BRParticleSummary)
        assert br.generator_count == 3
        assert br.texture_count == 2


class TestGcToBlender:

    def test_forward_transform(self):
        assert _gc_to_blender((1.0, 2.0, 3.0)) == (1.0, -3.0, 2.0)

    def test_zero_stays_zero(self):
        assert _gc_to_blender((0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0)
