"""Build Blender camera objects from IRCamera dataclasses."""
import math
import bpy
from mathutils import Matrix, Vector

try:
    from .....shared.IR.enums import CameraProjection, Interpolation
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.enums import CameraProjection, Interpolation
    from shared.helpers.logger import StubLogger


def _scene_model_size():
    """Compute the diagonal of the bounding box of all mesh objects in the scene."""
    min_co = [float('inf')] * 3
    max_co = [float('-inf')] * 3
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            for corner in obj.bound_box:
                world = obj.matrix_world @ Vector(corner)
                for i in range(3):
                    min_co[i] = min(min_co[i], world[i])
                    max_co[i] = max(max_co[i], world[i])
    if min_co[0] == float('inf'):
        return 1.0
    return (Vector(max_co) - Vector(min_co)).length

# Blender interpolation mode strings from IR Interpolation enum
_INTERP_MAP = {
    Interpolation.CONSTANT: 'CONSTANT',
    Interpolation.LINEAR: 'LINEAR',
    Interpolation.BEZIER: 'BEZIER',
}


def build_cameras(ir_cameras, logger):
    """Create Blender cameras from IRCamera list."""
    for ir_cam in ir_cameras:
        _build_camera(ir_cam, logger)
    if ir_cameras:
        logger.info("  Built %d camera(s)", len(ir_cameras))


def _build_camera(ir_cam, logger=StubLogger()):
    """Create a single Blender camera from IRCamera."""
    cam_data = bpy.data.cameras.new(name=ir_cam.name)

    if ir_cam.projection == CameraProjection.ORTHO:
        cam_data.type = 'ORTHO'
        cam_data.ortho_scale = ir_cam.field_of_view
    else:
        cam_data.type = 'PERSP'
        cam_data.sensor_fit = 'VERTICAL'
        cam_data.sensor_height = 18.0
        if ir_cam.field_of_view > 0:
            cam_data.lens = 18.0 / (2.0 * math.tan(math.radians(ir_cam.field_of_view) / 2.0))

    cam_data.clip_start = ir_cam.near
    cam_data.clip_end = ir_cam.far

    cam_obj = bpy.data.objects.new(name=ir_cam.name, object_data=cam_data)
    cam_obj["dat_camera_aspect"] = ir_cam.aspect

    if ir_cam.position:
        cam_obj.matrix_basis = (Matrix.Translation(Vector(ir_cam.position))
                                @ Matrix.Rotation(-math.pi / 2, 4, [1.0, 0.0, 0.0]))

    target_obj = None
    if ir_cam.target_position:
        target_obj = bpy.data.objects.new(ir_cam.name + '_target', None)
        target_obj.empty_display_type = 'PLAIN_AXES'
        target_obj.empty_display_size = max(0.1, min(3.0, _scene_model_size() * 0.03))
        target_obj.matrix_basis = Matrix.Translation(Vector(ir_cam.target_position))
        bpy.context.scene.collection.objects.link(target_obj)

        constraint = cam_obj.constraints.new(type='TRACK_TO')
        constraint.target = target_obj
        constraint.track_axis = 'TRACK_NEGATIVE_Z'
        constraint.up_axis = 'UP_Y'

    bpy.context.scene.collection.objects.link(cam_obj)

    # Coordinate system rotation (GameCube Y-up -> Blender Z-up)
    cam_obj.matrix_basis @= Matrix.Rotation(math.pi / 2, 4, [1.0, 0.0, 0.0])

    # Build camera animations
    if ir_cam.animations:
        _build_camera_animations(ir_cam, cam_obj, target_obj, cam_data, logger)


def _build_camera_animations(ir_cam, cam_obj, target_obj, cam_data, logger):
    """Create Blender Actions from IRCameraKeyframes list.

    Args:
        ir_cam: IRCamera with populated animations list.
        cam_obj: Blender camera object (for location/rotation keyframes).
        target_obj: Blender empty for track-to target (may be None).
        cam_data: Blender Camera data (for lens/clip keyframes).
        logger: Logger instance.
    """
    sensor_h = cam_data.sensor_height if hasattr(cam_data, 'sensor_height') else 18.0

    for anim in ir_cam.animations:
        action = bpy.data.actions.new(anim.name)
        action.use_fake_user = True

        # Eye position keyframes -> camera object location
        # GC coordinate rotation: (x, y, z) -> (x, z, -y)
        _insert_keyframes(action, 'location', 0, anim.eye_x, _gc_to_blender_x)
        _insert_keyframes(action, 'location', 1, anim.eye_z, _gc_to_blender_y)
        _insert_keyframes(action, 'location', 2, anim.eye_y, _gc_to_blender_z)

        # FOV -> lens focal length
        if anim.fov:
            _insert_keyframes(action, 'data.lens', 0, anim.fov,
                              lambda v: _fov_to_lens(v, sensor_h))

        # Roll -> rotation_euler Z
        if anim.roll:
            _insert_keyframes(action, 'rotation_euler', 2, anim.roll)

        # Near/far -> clip planes
        _insert_keyframes(action, 'data.clip_start', 0, anim.near)
        _insert_keyframes(action, 'data.clip_end', 0, anim.far)

        # Assign action to camera object
        if not cam_obj.animation_data:
            cam_obj.animation_data_create()
        cam_obj.animation_data.action = action

        # Target position keyframes -> track-to empty location
        if target_obj and (anim.target_x or anim.target_y or anim.target_z):
            target_action = bpy.data.actions.new(anim.name + '_target')
            target_action.use_fake_user = True

            _insert_keyframes(target_action, 'location', 0, anim.target_x, _gc_to_blender_x)
            _insert_keyframes(target_action, 'location', 1, anim.target_z, _gc_to_blender_y)
            _insert_keyframes(target_action, 'location', 2, anim.target_y, _gc_to_blender_z)

            if not target_obj.animation_data:
                target_obj.animation_data_create()
            target_obj.animation_data.action = target_action

        logger.info("  Camera animation '%s': end_frame=%.1f, loop=%s",
                    anim.name, anim.end_frame, anim.loop)


def _insert_keyframes(action, data_path, index, keyframes, transform=None):
    """Insert a list of IRKeyframe into an Action's FCurve.

    Args:
        action: Blender Action to insert into.
        data_path: FCurve data path (e.g. 'location', 'data.lens').
        index: FCurve array index.
        keyframes: list[IRKeyframe] or None.
        transform: Optional callable to transform keyframe values.
    """
    if not keyframes:
        return

    fcurve = action.fcurves.new(data_path, index=index)
    for kf in keyframes:
        value = transform(kf.value) if transform else kf.value
        point = fcurve.keyframe_points.insert(kf.frame, value)
        point.interpolation = _INTERP_MAP.get(kf.interpolation, 'LINEAR')


def _gc_to_blender_x(v):
    """GC X -> Blender X (unchanged)."""
    return v


def _gc_to_blender_y(v):
    """GC Z -> Blender Y (sign flip for coordinate rotation)."""
    return -v


def _gc_to_blender_z(v):
    """GC Y -> Blender Z (unchanged, just axis swap)."""
    return v


def _fov_to_lens(fov_degrees, sensor_height):
    """Convert vertical FOV in degrees to Blender focal length in mm."""
    if fov_degrees <= 0 or fov_degrees >= 180:
        return 50.0  # Blender default
    return sensor_height / (2.0 * math.tan(math.radians(fov_degrees) / 2.0))
