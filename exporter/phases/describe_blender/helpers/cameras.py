"""Describe Blender camera objects as IRCamera dataclasses.

Reads camera objects from the Blender scene and produces IRCamera list.
Handles PERSP and ORTHO camera types.
"""
import math
import bpy

try:
    from .....shared.IR.camera import IRCamera, IRCameraKeyframes
    from .....shared.IR.animation import IRKeyframe
    from .....shared.IR.enums import CameraProjection, Interpolation
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.camera import IRCamera, IRCameraKeyframes
    from shared.IR.animation import IRKeyframe
    from shared.IR.enums import CameraProjection, Interpolation
    from shared.helpers.logger import StubLogger


_BLENDER_TYPE_TO_IR = {
    'PERSP': CameraProjection.PERSPECTIVE,
    'ORTHO': CameraProjection.ORTHO,
}

_INTERP_TO_IR = {
    'CONSTANT': Interpolation.CONSTANT,
    'LINEAR': Interpolation.LINEAR,
    'BEZIER': Interpolation.BEZIER,
}


def describe_cameras(context, logger=StubLogger()):
    """Read Blender camera objects and produce IRCamera list.

    Args:
        context: Blender context with active scene.
        logger: Logger instance.

    Returns:
        list[IRCamera]
    """
    cameras = []

    for obj in bpy.data.objects:
        if obj.type != 'CAMERA':
            continue

        if obj.hide_viewport or obj.hide_get():
            logger.debug("  Skipping camera '%s': hidden", obj.name)
            continue

        ir_projection = _BLENDER_TYPE_TO_IR.get(obj.data.type)
        if ir_projection is None:
            logger.debug("  Skipping camera '%s': unsupported type '%s'", obj.name, obj.data.type)
            continue

        if ir_projection == CameraProjection.ORTHO:
            field_of_view = obj.data.ortho_scale
        else:
            # Reverse FOV conversion: vertical FOV from sensor_height and lens
            sensor_h = obj.data.sensor_height if obj.data.sensor_fit == 'VERTICAL' else 18.0
            if obj.data.lens > 0:
                field_of_view = math.degrees(2.0 * math.atan(sensor_h / (2.0 * obj.data.lens)))
            else:
                field_of_view = 60.0

        # Position: convert Blender Z-up to IR Y-up: (x, y, z) → (x, z, -y)
        pos = obj.location
        position = (pos.x, pos.z, -pos.y)

        # Target position from TRACK_TO constraint
        target_position = None
        target_obj = None
        for constraint in obj.constraints:
            if constraint.type == 'TRACK_TO' and constraint.target:
                target_obj = constraint.target
                t = target_obj.location
                target_position = (t.x, t.z, -t.y)
                break

        ir_cam = IRCamera(
            name=obj.name,
            projection=ir_projection,
            position=position,
            target_position=target_position,
            roll=0.0,
            near=obj.data.clip_start,
            far=obj.data.clip_end,
            field_of_view=field_of_view,
            aspect=obj.get("dat_camera_aspect", 1.333),
        )

        # Describe camera animations
        ir_cam.animations = _describe_camera_animations(obj, target_obj, logger)

        cameras.append(ir_cam)

    if cameras:
        logger.info("  Described %d camera(s)", len(cameras))
    return cameras


def _describe_camera_animations(cam_obj, target_obj, logger):
    """Read Blender camera FCurves and produce IRCameraKeyframes list.

    Args:
        cam_obj: Blender camera object.
        target_obj: Blender target empty (may be None).
        logger: Logger instance.

    Returns:
        list[IRCameraKeyframes]
    """
    anim_data = cam_obj.animation_data
    if not anim_data or not anim_data.action:
        return []

    action = anim_data.action
    sensor_h = cam_obj.data.sensor_height if cam_obj.data.sensor_fit == 'VERTICAL' else 18.0

    tracks = {}

    # Eye position: location channels with inverse coord rotation
    # Blender (x, y, z) -> GC (x, z, -y)
    _extract_fcurve(action, 'location', 0, 'eye_x', tracks, _blender_x_to_gc)
    _extract_fcurve(action, 'location', 2, 'eye_y', tracks, _blender_z_to_gc)
    _extract_fcurve(action, 'location', 1, 'eye_z', tracks, _blender_y_to_gc)

    # Lens -> FOV
    _extract_fcurve(action, 'data.lens', 0, 'fov', tracks,
                    lambda v: _lens_to_fov(v, sensor_h))

    # Roll from rotation_euler Z
    _extract_fcurve(action, 'rotation_euler', 2, 'roll', tracks)

    # Clip planes
    _extract_fcurve(action, 'data.clip_start', 0, 'near', tracks)
    _extract_fcurve(action, 'data.clip_end', 0, 'far', tracks)

    # Target position from the target empty's action
    if target_obj and target_obj.animation_data and target_obj.animation_data.action:
        target_action = target_obj.animation_data.action
        _extract_fcurve(target_action, 'location', 0, 'target_x', tracks, _blender_x_to_gc)
        _extract_fcurve(target_action, 'location', 2, 'target_y', tracks, _blender_z_to_gc)
        _extract_fcurve(target_action, 'location', 1, 'target_z', tracks, _blender_y_to_gc)

    if not tracks:
        return []

    # Compute end_frame from maximum keyframe frame across all tracks
    end_frame = 0.0
    for keyframes in tracks.values():
        if keyframes:
            end_frame = max(end_frame, max(kf.frame for kf in keyframes))

    ir_kf = IRCameraKeyframes(
        name=action.name,
        end_frame=end_frame,
        **tracks,
    )
    logger.debug("  Camera animation '%s': %d tracks, end_frame=%.1f",
                 action.name, len(tracks), end_frame)
    return [ir_kf]


def _extract_fcurve(action, data_path, index, field_name, tracks, transform=None):
    """Extract keyframes from an FCurve into the tracks dict.

    Args:
        action: Blender Action.
        data_path: FCurve data_path string.
        index: FCurve array_index.
        field_name: Key for the tracks dict.
        tracks: Output dict to populate.
        transform: Optional value transform callable.
    """
    fcurve = action.fcurves.find(data_path, index=index)
    if not fcurve or not fcurve.keyframe_points:
        return

    keyframes = []
    for kp in fcurve.keyframe_points:
        value = transform(kp.co[1]) if transform else kp.co[1]
        interp = _INTERP_TO_IR.get(kp.interpolation, Interpolation.LINEAR)
        keyframes.append(IRKeyframe(
            frame=kp.co[0],
            value=value,
            interpolation=interp,
        ))

    if keyframes:
        tracks[field_name] = keyframes


def _blender_x_to_gc(v):
    """Blender X -> GC X (unchanged)."""
    return v


def _blender_y_to_gc(v):
    """Blender Y -> GC Z (sign flip for coordinate rotation)."""
    return -v


def _blender_z_to_gc(v):
    """Blender Z -> GC Y (unchanged, just axis swap)."""
    return v


def _lens_to_fov(lens_mm, sensor_height):
    """Convert Blender focal length in mm to vertical FOV in degrees."""
    if lens_mm <= 0:
        return 60.0
    return math.degrees(2.0 * math.atan(sensor_height / (2.0 * lens_mm)))
