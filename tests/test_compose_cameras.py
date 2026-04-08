"""Tests for exporter/phases/compose/helpers/cameras.py — camera composition."""
from exporter.phases.compose.helpers.cameras import compose_camera
from shared.IR.camera import IRCamera, IRCameraKeyframes
from shared.IR.animation import IRKeyframe
from shared.IR.enums import CameraProjection, Interpolation
from shared.Constants.hsd import (
    COBJ_PROJECTION_PERSPECTIVE, COBJ_PROJECTION_ORTHO,
    HSD_A_C_FOVY, HSD_A_C_ROLL, HSD_A_C_NEAR, HSD_A_C_FAR,
    HSD_A_W_TRAX, HSD_A_W_TRAY, HSD_A_W_TRAZ,
    AOBJ_ANIM_LOOP,
)


def _make_ir_camera(**kwargs):
    defaults = dict(
        name="Camera_0",
        projection=CameraProjection.PERSPECTIVE,
        position=(1.0, 2.0, 3.0),
        target_position=(0.0, 0.0, 0.0),
        roll=0.0,
        near=0.1,
        far=32768.0,
        field_of_view=27.0,
        aspect=1.18,
    )
    defaults.update(kwargs)
    return IRCamera(**defaults)


def _make_keyframes(values):
    """Create a list of IRKeyframe at consecutive integer frames."""
    return [
        IRKeyframe(frame=float(i), value=v, interpolation=Interpolation.LINEAR)
        for i, v in enumerate(values)
    ]


class TestComposeCamera:

    def test_returns_none_for_none(self):
        assert compose_camera(None) is None

    def test_perspective_flags(self):
        ir_cam = _make_ir_camera(projection=CameraProjection.PERSPECTIVE)
        result = compose_camera(ir_cam)
        assert result.camera.perspective_flags == COBJ_PROJECTION_PERSPECTIVE

    def test_ortho_flags(self):
        ir_cam = _make_ir_camera(projection=CameraProjection.ORTHO)
        result = compose_camera(ir_cam)
        assert result.camera.perspective_flags == COBJ_PROJECTION_ORTHO

    def test_position_flows_to_wobject(self):
        ir_cam = _make_ir_camera(position=(10.0, 20.0, 30.0))
        result = compose_camera(ir_cam)
        assert result.camera.position.position == [10.0, 20.0, 30.0]

    def test_interest_flows_to_wobject(self):
        ir_cam = _make_ir_camera(target_position=(5.0, 6.0, 7.0))
        result = compose_camera(ir_cam)
        assert result.camera.interest.position == [5.0, 6.0, 7.0]

    def test_fov_preserved(self):
        ir_cam = _make_ir_camera(field_of_view=40.0)
        result = compose_camera(ir_cam)
        assert result.camera.field_of_view == 40.0

    def test_clip_planes(self):
        ir_cam = _make_ir_camera(near=0.5, far=1000.0)
        result = compose_camera(ir_cam)
        assert result.camera.near == 0.5
        assert result.camera.far == 1000.0

    def test_roll_preserved(self):
        ir_cam = _make_ir_camera(roll=0.3)
        result = compose_camera(ir_cam)
        assert result.camera.roll == 0.3

    def test_aspect_preserved(self):
        ir_cam = _make_ir_camera(aspect=1.5)
        result = compose_camera(ir_cam)
        assert result.camera.aspect == 1.5

    def test_camera_set_structure(self):
        ir_cam = _make_ir_camera()
        result = compose_camera(ir_cam)
        assert result.camera is not None
        assert result.animations is None

    def test_default_viewport_scissor(self):
        ir_cam = _make_ir_camera()
        result = compose_camera(ir_cam)
        assert result.camera.viewport == [0, 640, 0, 480]
        assert result.camera.scissor == [0, 640, 0, 480]


class TestComposeCameraAnimations:

    def test_no_animations_gives_none(self):
        ir_cam = _make_ir_camera()
        result = compose_camera(ir_cam)
        assert result.animations is None

    def test_fov_animation_creates_cobj_aobj(self):
        anim = IRCameraKeyframes(
            name="CamAnim_0_00",
            fov=_make_keyframes([30.0, 45.0, 60.0]),
            end_frame=2.0,
        )
        ir_cam = _make_ir_camera(animations=[anim])
        result = compose_camera(ir_cam)

        assert result.animations is not None
        assert len(result.animations) == 1
        cam_anim = result.animations[0]
        assert cam_anim.animation is not None
        assert cam_anim.animation.end_frame == 2.0

        # Should have a Frame node with type HSD_A_C_FOVY
        frame = cam_anim.animation.frame
        assert frame is not None
        assert frame.type == HSD_A_C_FOVY

    def test_loop_flag_set(self):
        anim = IRCameraKeyframes(
            name="CamAnim_0_00",
            fov=_make_keyframes([30.0]),
            end_frame=10.0,
            loop=True,
        )
        ir_cam = _make_ir_camera(animations=[anim])
        result = compose_camera(ir_cam)
        cam_anim = result.animations[0]
        assert cam_anim.animation.flags & AOBJ_ANIM_LOOP

    def test_no_loop_flag(self):
        anim = IRCameraKeyframes(
            name="CamAnim_0_00",
            fov=_make_keyframes([30.0]),
            end_frame=10.0,
            loop=False,
        )
        ir_cam = _make_ir_camera(animations=[anim])
        result = compose_camera(ir_cam)
        cam_anim = result.animations[0]
        assert not (cam_anim.animation.flags & AOBJ_ANIM_LOOP)

    def test_eye_position_creates_wobject_animation(self):
        anim = IRCameraKeyframes(
            name="CamAnim_0_00",
            eye_x=_make_keyframes([10.0, 20.0]),
            eye_y=_make_keyframes([30.0, 40.0]),
            eye_z=_make_keyframes([50.0, 60.0]),
            end_frame=1.0,
        )
        ir_cam = _make_ir_camera(animations=[anim])
        result = compose_camera(ir_cam)
        cam_anim = result.animations[0]

        assert cam_anim.eye_position_animation is not None
        wobj_anim = cam_anim.eye_position_animation
        assert wobj_anim.animation is not None
        assert wobj_anim.animation.end_frame == 1.0

        # Walk the frame chain to check types
        types = set()
        f = wobj_anim.animation.frame
        while f:
            types.add(f.type)
            f = f.next
        assert HSD_A_W_TRAX in types
        assert HSD_A_W_TRAY in types
        assert HSD_A_W_TRAZ in types

    def test_target_position_creates_wobject_animation(self):
        anim = IRCameraKeyframes(
            name="CamAnim_0_00",
            target_x=_make_keyframes([1.0, 2.0]),
            target_y=_make_keyframes([3.0, 4.0]),
            end_frame=1.0,
        )
        ir_cam = _make_ir_camera(animations=[anim])
        result = compose_camera(ir_cam)
        cam_anim = result.animations[0]

        assert cam_anim.interest_animation is not None
        types = set()
        f = cam_anim.interest_animation.animation.frame
        while f:
            types.add(f.type)
            f = f.next
        assert HSD_A_W_TRAX in types
        assert HSD_A_W_TRAY in types

    def test_multiple_cobj_tracks_chained(self):
        anim = IRCameraKeyframes(
            name="CamAnim_0_00",
            fov=_make_keyframes([30.0, 45.0]),
            roll=_make_keyframes([0.0, 0.5]),
            near=_make_keyframes([0.1, 0.5]),
            far=_make_keyframes([1000.0, 5000.0]),
            end_frame=1.0,
        )
        ir_cam = _make_ir_camera(animations=[anim])
        result = compose_camera(ir_cam)
        cam_anim = result.animations[0]

        types = set()
        f = cam_anim.animation.frame
        while f:
            types.add(f.type)
            f = f.next
        assert HSD_A_C_FOVY in types
        assert HSD_A_C_ROLL in types
        assert HSD_A_C_NEAR in types
        assert HSD_A_C_FAR in types

    def test_only_eye_no_cobj_aobj(self):
        """When only eye position exists, CObj AOBJ should be None."""
        anim = IRCameraKeyframes(
            name="CamAnim_0_00",
            eye_x=_make_keyframes([10.0]),
            end_frame=0.0,
        )
        ir_cam = _make_ir_camera(animations=[anim])
        result = compose_camera(ir_cam)
        cam_anim = result.animations[0]
        assert cam_anim.animation is None
        assert cam_anim.eye_position_animation is not None

    def test_no_target_gives_none_interest(self):
        anim = IRCameraKeyframes(
            name="CamAnim_0_00",
            fov=_make_keyframes([30.0]),
            end_frame=0.0,
        )
        ir_cam = _make_ir_camera(animations=[anim])
        result = compose_camera(ir_cam)
        cam_anim = result.animations[0]
        assert cam_anim.interest_animation is None

    def test_multiple_animations(self):
        anim1 = IRCameraKeyframes(
            name="CamAnim_0_00",
            fov=_make_keyframes([30.0]),
            end_frame=5.0,
        )
        anim2 = IRCameraKeyframes(
            name="CamAnim_0_01",
            fov=_make_keyframes([60.0]),
            end_frame=10.0,
        )
        ir_cam = _make_ir_camera(animations=[anim1, anim2])
        result = compose_camera(ir_cam)
        assert len(result.animations) == 2
