"""Tests for importer/phases/describe/helpers/cameras.py — camera description."""
from types import SimpleNamespace

from importer.phases.describe.helpers.cameras import describe_camera, describe_camera_animations
from shared.helpers.scale import GC_TO_METERS as S
from shared.IR.enums import CameraProjection, Interpolation
from shared.IR.camera import IRCameraKeyframes
from shared.Constants.hsd import (
    COBJ_PROJECTION_PERSPECTIVE, COBJ_PROJECTION_FRUSTUM, COBJ_PROJECTION_ORTHO,
    HSD_A_C_FOVY, HSD_A_C_ROLL, HSD_A_C_NEAR, HSD_A_C_FAR,
    HSD_A_C_EYEX, HSD_A_C_EYEY, HSD_A_C_EYEZ,
    HSD_A_C_ATX, HSD_A_C_ATY, HSD_A_C_ATZ,
    HSD_A_W_TRAX, HSD_A_W_TRAY, HSD_A_W_TRAZ,
    HSD_A_OP_LIN, HSD_A_FRAC_FLOAT,
    AOBJ_ANIM_LOOP,
)
from shared.helpers.binary import pack_native


def _make_wobject(position):
    return SimpleNamespace(position=position)


def _make_camera(persp_flags=COBJ_PROJECTION_PERSPECTIVE, name=None,
                 position=None, interest=None,
                 roll=0.0, near=0.1, far=32768.0,
                 field_of_view=27.0, aspect=1.18):
    return SimpleNamespace(
        name=name,
        flags=0,
        perspective_flags=persp_flags,
        position=_make_wobject(position) if position else None,
        interest=_make_wobject(interest) if interest else None,
        roll=roll,
        near=near,
        far=far,
        field_of_view=field_of_view,
        aspect=aspect,
    )


def _make_frame(fobj_type, values):
    """Build a mock Frame node with raw_ad encoding LIN keyframes at integer frames.

    Each value gets a LIN opcode + float value + wait=1 (except last wait=0).
    """
    raw = bytearray()
    count = len(values)
    # Encode one LIN opcode for the entire run
    first_3 = (count - 1) & 7
    remaining = (count - 1) >> 3
    first_byte = HSD_A_OP_LIN | (first_3 << 4)
    if remaining > 0:
        first_byte |= 0x80
    raw.append(first_byte)
    while remaining > 0:
        ext = remaining & 0x7F
        remaining >>= 7
        if remaining > 0:
            ext |= 0x80
        raw.append(ext)

    # Encode each value + wait
    for i, v in enumerate(values):
        raw.extend(pack_native('float', v))
        wait = 1 if i < count - 1 else 0
        raw.append(wait)

    return SimpleNamespace(
        type=fobj_type,
        frac_value=HSD_A_FRAC_FLOAT,
        frac_slope=HSD_A_FRAC_FLOAT,
        start_frame=0.0,
        raw_ad=bytes(raw),
        data_length=len(raw),
        next=None,
    )


def _chain_frames(*frames):
    """Link Frame mocks into a linked list."""
    for i in range(len(frames) - 1):
        frames[i].next = frames[i + 1]
    return frames[0] if frames else None


def _make_aobj(end_frame=10.0, flags=0, frame=None):
    return SimpleNamespace(
        end_frame=end_frame,
        flags=flags,
        frame=frame,
    )


def _make_wobject_animation(aobj=None):
    return SimpleNamespace(
        animation=aobj,
        render_animation=None,
    )


def _make_camera_animation(aobj=None, eye_wobj_anim=None, interest_wobj_anim=None):
    return SimpleNamespace(
        animation=aobj,
        eye_position_animation=eye_wobj_anim,
        interest_animation=interest_wobj_anim,
    )


def _make_camera_set(camera=None, animations=None):
    return SimpleNamespace(
        camera=camera,
        animations=animations,
    )


class TestDescribeCamera:

    def test_perspective_camera(self):
        cam = _make_camera(persp_flags=COBJ_PROJECTION_PERSPECTIVE)
        result = describe_camera(cam)
        assert result is not None
        assert result.projection == CameraProjection.PERSPECTIVE

    def test_frustum_maps_to_perspective(self):
        cam = _make_camera(persp_flags=COBJ_PROJECTION_FRUSTUM)
        result = describe_camera(cam)
        assert result is not None
        assert result.projection == CameraProjection.PERSPECTIVE

    def test_ortho_camera(self):
        cam = _make_camera(persp_flags=COBJ_PROJECTION_ORTHO)
        result = describe_camera(cam)
        assert result is not None
        assert result.projection == CameraProjection.ORTHO

    def test_unrecognized_flags_returns_none(self):
        cam = _make_camera(persp_flags=99)
        result = describe_camera(cam)
        assert result is None

    def test_position_extracted(self):
        cam = _make_camera(position=(1.0, 2.0, 3.0))
        result = describe_camera(cam)
        assert result.position == (1.0 * S, 2.0 * S, 3.0 * S)

    def test_target_position(self):
        cam = _make_camera(interest=(4.0, 5.0, 6.0))
        result = describe_camera(cam)
        assert result.target_position == (4.0 * S, 5.0 * S, 6.0 * S)

    def test_no_position(self):
        cam = _make_camera()
        result = describe_camera(cam)
        assert result.position is None
        assert result.target_position is None

    def test_clip_planes(self):
        cam = _make_camera(near=0.5, far=1000.0)
        result = describe_camera(cam)
        assert abs(result.near - 0.5 * S) < 1e-6
        assert abs(result.far - 1000.0 * S) < 1e-3

    def test_fov_preserved(self):
        cam = _make_camera(field_of_view=40.0)
        result = describe_camera(cam)
        assert result.field_of_view == 40.0

    def test_aspect_preserved(self):
        cam = _make_camera(aspect=1.333)
        result = describe_camera(cam)
        assert result.aspect == 1.333

    def test_roll_preserved(self):
        cam = _make_camera(roll=0.5)
        result = describe_camera(cam)
        assert result.roll == 0.5

    def test_name_first_camera(self):
        cam = _make_camera(name="battle_cam")
        result = describe_camera(cam, camera_index=0)
        assert result.name == "Battle_Camera"

    def test_name_subsequent_camera(self):
        cam = _make_camera(name=None)
        result = describe_camera(cam, camera_index=3)
        assert result.name == "Camera_3"


class TestDescribeCameraAnimations:

    def test_empty_animations_returns_empty(self):
        cs = _make_camera_set(animations=None)
        result = describe_camera_animations(cs)
        assert result == []

    def test_empty_list_returns_empty(self):
        cs = _make_camera_set(animations=[])
        result = describe_camera_animations(cs)
        assert result == []

    def test_fov_track_decoded(self):
        fov_frame = _make_frame(HSD_A_C_FOVY, [27.0, 40.0, 55.0])
        aobj = _make_aobj(end_frame=2.0, frame=fov_frame)
        cam_anim = _make_camera_animation(aobj=aobj)
        cs = _make_camera_set(animations=[cam_anim])

        result = describe_camera_animations(cs)
        assert len(result) == 1
        assert result[0].fov is not None
        assert len(result[0].fov) == 3
        assert abs(result[0].fov[0].value - 27.0) < 0.01
        assert abs(result[0].fov[2].value - 55.0) < 0.01

    def test_end_frame_and_loop(self):
        fov_frame = _make_frame(HSD_A_C_FOVY, [30.0])
        aobj = _make_aobj(end_frame=100.0, flags=AOBJ_ANIM_LOOP, frame=fov_frame)
        cam_anim = _make_camera_animation(aobj=aobj)
        cs = _make_camera_set(animations=[cam_anim])

        result = describe_camera_animations(cs)
        assert result[0].end_frame == 100.0
        assert result[0].loop is True

    def test_no_loop(self):
        fov_frame = _make_frame(HSD_A_C_FOVY, [30.0])
        aobj = _make_aobj(end_frame=50.0, flags=0, frame=fov_frame)
        cam_anim = _make_camera_animation(aobj=aobj)
        cs = _make_camera_set(animations=[cam_anim])

        result = describe_camera_animations(cs)
        assert result[0].loop is False

    def test_multiple_cobj_tracks(self):
        fov_frame = _make_frame(HSD_A_C_FOVY, [30.0, 45.0])
        roll_frame = _make_frame(HSD_A_C_ROLL, [0.0, 0.5])
        _chain_frames(fov_frame, roll_frame)
        aobj = _make_aobj(end_frame=1.0, frame=fov_frame)
        cam_anim = _make_camera_animation(aobj=aobj)
        cs = _make_camera_set(animations=[cam_anim])

        result = describe_camera_animations(cs)
        assert result[0].fov is not None
        assert result[0].roll is not None

    def test_near_far_tracks(self):
        near_frame = _make_frame(HSD_A_C_NEAR, [0.1, 0.5])
        far_frame = _make_frame(HSD_A_C_FAR, [1000.0, 5000.0])
        _chain_frames(near_frame, far_frame)
        aobj = _make_aobj(end_frame=1.0, frame=near_frame)
        cam_anim = _make_camera_animation(aobj=aobj)
        cs = _make_camera_set(animations=[cam_anim])

        result = describe_camera_animations(cs)
        assert result[0].near is not None
        assert result[0].far is not None

    def test_eye_position_from_wobject_animation(self):
        eye_x = _make_frame(HSD_A_W_TRAX, [10.0, 20.0])
        eye_y = _make_frame(HSD_A_W_TRAY, [30.0, 40.0])
        eye_z = _make_frame(HSD_A_W_TRAZ, [50.0, 60.0])
        _chain_frames(eye_x, eye_y, eye_z)
        eye_aobj = _make_aobj(end_frame=1.0, frame=eye_x)
        eye_wobj = _make_wobject_animation(aobj=eye_aobj)
        cam_anim = _make_camera_animation(eye_wobj_anim=eye_wobj)
        cs = _make_camera_set(animations=[cam_anim])

        result = describe_camera_animations(cs)
        assert len(result) == 1
        assert result[0].eye_x is not None
        assert len(result[0].eye_x) == 2
        assert abs(result[0].eye_x[0].value - 10.0 * S) < 0.01
        assert result[0].eye_y is not None
        assert result[0].eye_z is not None

    def test_target_position_from_wobject_animation(self):
        tgt_x = _make_frame(HSD_A_W_TRAX, [1.0, 2.0])
        tgt_y = _make_frame(HSD_A_W_TRAY, [3.0, 4.0])
        _chain_frames(tgt_x, tgt_y)
        tgt_aobj = _make_aobj(end_frame=1.0, frame=tgt_x)
        tgt_wobj = _make_wobject_animation(aobj=tgt_aobj)
        cam_anim = _make_camera_animation(interest_wobj_anim=tgt_wobj)
        cs = _make_camera_set(animations=[cam_anim])

        result = describe_camera_animations(cs)
        assert len(result) == 1
        assert result[0].target_x is not None
        assert result[0].target_y is not None

    def test_combined_cobj_and_wobject_tracks(self):
        """CObj AOBJ has FOV, WObj has eye position."""
        fov_frame = _make_frame(HSD_A_C_FOVY, [30.0])
        aobj = _make_aobj(end_frame=5.0, frame=fov_frame)

        eye_x = _make_frame(HSD_A_W_TRAX, [100.0])
        eye_aobj = _make_aobj(end_frame=5.0, frame=eye_x)
        eye_wobj = _make_wobject_animation(aobj=eye_aobj)

        cam_anim = _make_camera_animation(aobj=aobj, eye_wobj_anim=eye_wobj)
        cs = _make_camera_set(animations=[cam_anim])

        result = describe_camera_animations(cs)
        assert result[0].fov is not None
        assert result[0].eye_x is not None

    def test_multiple_camera_animations(self):
        fov1 = _make_frame(HSD_A_C_FOVY, [30.0])
        aobj1 = _make_aobj(end_frame=10.0, frame=fov1)
        cam_anim1 = _make_camera_animation(aobj=aobj1)

        fov2 = _make_frame(HSD_A_C_FOVY, [60.0])
        aobj2 = _make_aobj(end_frame=20.0, frame=fov2)
        cam_anim2 = _make_camera_animation(aobj=aobj2)

        cs = _make_camera_set(animations=[cam_anim1, cam_anim2])
        result = describe_camera_animations(cs)
        assert len(result) == 2

    def test_no_aobj_no_wobject_returns_empty(self):
        cam_anim = _make_camera_animation()
        cs = _make_camera_set(animations=[cam_anim])
        result = describe_camera_animations(cs)
        assert result == []

    def test_wobject_end_frame_fallback(self):
        """When CObj AOBJ is missing, end_frame comes from WObj AOBJ."""
        eye_x = _make_frame(HSD_A_W_TRAX, [10.0])
        eye_aobj = _make_aobj(end_frame=42.0, frame=eye_x)
        eye_wobj = _make_wobject_animation(aobj=eye_aobj)
        cam_anim = _make_camera_animation(eye_wobj_anim=eye_wobj)
        cs = _make_camera_set(animations=[cam_anim])

        result = describe_camera_animations(cs)
        assert result[0].end_frame == 42.0
