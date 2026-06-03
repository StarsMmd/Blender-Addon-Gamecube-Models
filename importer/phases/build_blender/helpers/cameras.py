"""Build Blender cameras from a BR camera list. Pure bpy executor —
projection, FOV→lens conversion, coord rotation, and animation-keyframe
shaping are all done in the Plan phase.
"""
import bpy
from mathutils import Vector

try:
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def _scene_model_size():
    """Diagonal of the AABB of every MESH object in the current scene.

    In: (reads bpy.data.objects).
    Out: float, diagonal length in Blender units (1.0 fallback for empty scene).
    """
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


def build_cameras(br_cameras, logger):
    """Create Blender cameras for every BRCamera in the list.

    In: br_cameras (list[BRCamera]); logger (Logger).
    Out: None. Cameras + TRACK_TO target empties are linked into the scene.
    """
    for br_cam in br_cameras:
        _build_camera(br_cam, logger)
    if br_cameras:
        logger.info("  Built %d camera(s)", len(br_cameras))


def _build_camera(br_cam, logger=StubLogger()):
    """Build one camera object + data block from a BRCamera spec.

    In: br_cam (BRCamera); logger (Logger).
    Out: None. Camera object (and optional target empty + TRACK_TO constraint)
         are linked to the scene; per-animation Actions are attached too.
    """
    cam_data = bpy.data.cameras.new(name=br_cam.name)

    if br_cam.projection == 'ORTHO':
        cam_data.type = 'ORTHO'
        cam_data.ortho_scale = br_cam.lens  # lens field holds ortho_scale
    else:
        cam_data.type = 'PERSP'
        cam_data.sensor_fit = 'VERTICAL'
        cam_data.sensor_height = br_cam.sensor_height
        cam_data.lens = br_cam.lens

    cam_data.clip_start = br_cam.clip_start
    cam_data.clip_end = br_cam.clip_end

    cam_obj = bpy.data.objects.new(name=br_cam.name, object_data=cam_data)
    cam_obj["dat_camera_aspect"] = br_cam.aspect

    if br_cam.location is not None:
        cam_obj.location = br_cam.location

    target_obj = None
    if br_cam.target_location is not None:
        target_obj = bpy.data.objects.new(br_cam.name + '_target', None)
        target_obj.empty_display_type = 'PLAIN_AXES'
        target_obj.empty_display_size = max(0.1, min(3.0, _scene_model_size() * 0.03))
        target_obj.location = br_cam.target_location
        bpy.context.scene.collection.objects.link(target_obj)

        constraint = cam_obj.constraints.new(type='TRACK_TO')
        constraint.target = target_obj
        constraint.track_axis = 'TRACK_NEGATIVE_Z'
        constraint.up_axis = 'UP_Y'

    bpy.context.scene.collection.objects.link(cam_obj)

    for anim in br_cam.animations:
        _build_camera_animation(anim, cam_obj, target_obj, cam_data, logger)


def _build_camera_animation(anim, cam_obj, target_obj, cam_data, logger):
    """Assign per-action fcurves. All values in anim are pre-transformed
    into Blender space; this layer just inserts keyframes.

    In: anim (BRCameraAnimation); cam_obj (bpy.types.Object, camera);
        target_obj (bpy.types.Object|None, track-to empty);
        cam_data (bpy.types.Camera); logger (Logger).
    Out: None. Creates one Action for the camera and optionally a second
         Action for the target empty; both assigned via animation_data.
    """
    action = bpy.data.actions.new(anim.name)
    action.use_fake_user = True

    _insert_keyframes(action, 'location', 0, anim.loc_x)
    _insert_keyframes(action, 'location', 1, anim.loc_y)
    _insert_keyframes(action, 'location', 2, anim.loc_z)
    _insert_keyframes(action, 'rotation_euler', 2, anim.roll)
    _insert_keyframes(action, 'data.lens', 0, anim.lens)
    _insert_keyframes(action, 'data.clip_start', 0, anim.clip_start)
    _insert_keyframes(action, 'data.clip_end', 0, anim.clip_end)

    if not cam_obj.animation_data:
        cam_obj.animation_data_create()
    cam_obj.animation_data.action = action

    if target_obj and (anim.target_loc_x or anim.target_loc_y or anim.target_loc_z):
        target_action = bpy.data.actions.new(anim.name + '_target')
        target_action.use_fake_user = True
        _insert_keyframes(target_action, 'location', 0, anim.target_loc_x)
        _insert_keyframes(target_action, 'location', 1, anim.target_loc_y)
        _insert_keyframes(target_action, 'location', 2, anim.target_loc_z)
        if not target_obj.animation_data:
            target_obj.animation_data_create()
        target_obj.animation_data.action = target_action

    logger.info("  Camera animation '%s': end_frame=%.1f, loop=%s",
                anim.name, anim.end_frame, anim.loop)


def _insert_keyframes(action, data_path, index, keyframes):
    """Insert a list of IRKeyframe entries into one fcurve of an action.

    In: action (bpy.types.Action); data_path (str, e.g. 'location' or 'data.lens');
        index (int, array component); keyframes (list[IRKeyframe]|None).
    Out: None. No-op when keyframes is falsy.
    """
    if not keyframes:
        return
    fcurve = action.fcurves.new(data_path, index=index)
    for kf in keyframes:
        point = fcurve.keyframe_points.insert(kf.frame, kf.value)
        # IR keyframe interpolation enum values are Blender's own strings
        # ('CONSTANT', 'LINEAR', 'BEZIER'), so .value maps directly.
        point.interpolation = kf.interpolation.value
