"""Plan BRCamera list into IRCamera list.

Pure — no bpy. FOV is derived from BR.lens + sensor_height. Positions
flip from Blender Z-up to GameCube Y-up: Blender (x, y, z) → GC (x, z, -y).
Camera animations get the same axis swap on every keyframe value, plus
a per-frame lens→FOV conversion on the lens track.
"""
import math

try:
    from .....shared.IR.camera import IRCamera, IRCameraKeyframes
    from .....shared.IR.animation import IRKeyframe
    from .....shared.IR.enums import CameraProjection
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.camera import IRCamera, IRCameraKeyframes
    from shared.IR.animation import IRKeyframe
    from shared.IR.enums import CameraProjection
    from shared.helpers.logger import StubLogger


_PROJ_TO_IR = {
    'PERSP': CameraProjection.PERSPECTIVE,
    'ORTHO': CameraProjection.ORTHO,
}


def plan_cameras(br_cameras, logger=StubLogger()):
    """Convert BR cameras (Blender frame) into IR cameras (GC frame)."""
    out = []
    for br in br_cameras:
        ir_proj = _PROJ_TO_IR.get(br.projection)
        if ir_proj is None:
            continue

        if ir_proj == CameraProjection.ORTHO:
            field_of_view = br.lens  # BR.lens carries ortho_scale for ORTHO
        else:
            field_of_view = _lens_to_fov(br.lens, br.sensor_height)

        out.append(IRCamera(
            name=br.name,
            projection=ir_proj,
            position=_zup_to_yup(br.location),
            target_position=_zup_to_yup(br.target_location),
            roll=0.0,
            near=br.clip_start,
            far=br.clip_end,
            field_of_view=field_of_view,
            aspect=br.aspect,
            animations=[_plan_camera_animation(a, br.sensor_height) for a in br.animations],
        ))
    return out


def _plan_camera_animation(br_anim, sensor_h):
    """Map BR animation tracks (Blender frame, mm lens) into IR camera
    keyframes (GC frame, FOV degrees)."""
    return IRCameraKeyframes(
        name=br_anim.name,
        end_frame=br_anim.end_frame,
        loop=br_anim.loop,
        # Blender (x, y, z) → GC (x, z, -y):
        #   IR eye_x = Blender x        (unchanged)
        #   IR eye_y = Blender z        (unchanged)
        #   IR eye_z = -Blender y       (sign flip)
        eye_x=_passthrough(br_anim.loc_x),
        eye_y=_passthrough(br_anim.loc_z),
        eye_z=_negate(br_anim.loc_y),
        target_x=_passthrough(br_anim.target_loc_x),
        target_y=_passthrough(br_anim.target_loc_z),
        target_z=_negate(br_anim.target_loc_y),
        roll=_passthrough(br_anim.roll),
        fov=[_remap_keyframe(kf, lambda v: _lens_to_fov(v, sensor_h))
             for kf in br_anim.lens] if br_anim.lens else None,
        near=_passthrough(br_anim.clip_start),
        far=_passthrough(br_anim.clip_end),
    )


def _passthrough(keyframes):
    return list(keyframes) if keyframes else None


def _negate(keyframes):
    return [_remap_keyframe(kf, lambda v: -v) for kf in keyframes] if keyframes else None


def _remap_keyframe(kf, fn):
    return IRKeyframe(frame=kf.frame, value=fn(kf.value), interpolation=kf.interpolation)


def _zup_to_yup(p):
    if p is None:
        return None
    return (p[0], p[2], -p[1])


def _lens_to_fov(lens_mm, sensor_height):
    if lens_mm is None or lens_mm <= 0:
        return 60.0
    return math.degrees(2.0 * math.atan(sensor_height / (2.0 * lens_mm)))
