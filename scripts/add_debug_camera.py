"""Add a debug preview camera to the current Blender scene.

Self-contained — no imports from the plugin codebase. Drops a single
perspective camera (with TRACK_TO target empty) framed in front of the
scene's combined mesh AABB. The DAT exporter writes whatever cameras
are present in the scene, so anything added here will end up in the
output .dat / .pkx as a regular `scene_data.camera` entry — there is no
special "debug" handling on the export side.

Use when you need a viewport-friendly camera to inspect a model before
export, or when you want to author a real camera into the output file.

Run from Blender's Scripting tab:

    exec(open(bpy.path.abspath('//../scripts/add_debug_camera.py')).read())

Or pass a custom name:

    NAME = "MyPreview"; exec(...)
"""
import bpy
from mathutils import Vector


# Default name. Override before exec() if you want something else.
NAME = globals().get('NAME', 'Debug_Camera')


def _model_aabb():
    """Return ((min_x, min_y, min_z), (max_x, max_y, max_z)) over every
    MESH object in the scene, or (None, None) if there are no meshes.
    """
    min_co = [float('inf')] * 3
    max_co = [float('-inf')] * 3
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        for corner in obj.bound_box:
            world = obj.matrix_world @ Vector(corner)
            for i in range(3):
                if world[i] < min_co[i]:
                    min_co[i] = world[i]
                if world[i] > max_co[i]:
                    max_co[i] = world[i]
    if min_co[0] == float('inf'):
        return None, None
    return tuple(min_co), tuple(max_co)


def _display_size(min_co, max_co):
    if min_co is None:
        return 0.5
    diag = (Vector(max_co) - Vector(min_co)).length
    return max(0.1, min(3.0, diag * 0.03))


def add_debug_camera(name=NAME):
    """Add a perspective preview camera named ``name`` framed on the scene's
    meshes. Returns the new camera object (or the existing one with the
    same name, untouched).
    """
    if bpy.data.objects.get(name) is not None:
        print("Camera '%s' already exists — leaving it alone" % name)
        return bpy.data.objects[name]

    min_co, max_co = _model_aabb()
    if min_co is not None:
        center_x = (min_co[0] + max_co[0]) / 2
        center_y = (min_co[1] + max_co[1]) / 2
        height = max_co[2] - min_co[2]
        target_z = max_co[2] * 0.5
    else:
        center_x, center_y = 0.0, 0.0
        height = 1.0
        target_z = 0.5

    # In front of the model on the -Y axis, pulled back ~2.5× model height.
    cam_distance = max(height * 2.5, 1.5)
    cam_pos = (center_x, center_y - cam_distance, target_z)
    target_pos = (center_x, center_y, target_z)

    cam_data = bpy.data.cameras.new(name)
    cam_data.type = 'PERSP'
    cam_data.lens = 37.5
    cam_data.clip_start = 0.01
    cam_data.clip_end = 3277.0

    cam_obj = bpy.data.objects.new(name, cam_data)
    cam_obj.location = cam_pos
    cam_obj["dat_camera_aspect"] = 1.18
    bpy.context.scene.collection.objects.link(cam_obj)

    target = bpy.data.objects.new(name + '_target', None)
    target.empty_display_type = 'PLAIN_AXES'
    target.empty_display_size = _display_size(min_co, max_co)
    target.location = target_pos
    bpy.context.scene.collection.objects.link(target)

    track = cam_obj.constraints.new('TRACK_TO')
    track.target = target
    track.track_axis = 'TRACK_NEGATIVE_Z'
    track.up_axis = 'UP_Y'

    print("Created '%s' at (%.2f, %.2f, %.2f), targeting (%.2f, %.2f, %.2f)"
          % ((name,) + cam_pos + target_pos))
    print("  Lens: 37.5mm (~27° FOV), aspect: 1.18")
    print("  Edit the camera's location/lens to reframe.")
    return cam_obj


if __name__ == '__main__' or __name__ == 'add_debug_camera':
    add_debug_camera()
