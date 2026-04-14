"""Scale an IRScene from Blender meters to GameCube units in place.

The compose phase consumes IR data in GC units (the game's native scale);
the describe_blender phase emits IR data in meters (Blender's native scale).
Rather than leave every compose helper to remember the `* METERS_TO_GC`
conversion — which is how the bound box ended up in meters in the shipped
file — this module does the conversion once at the top of `compose_scene`,
so every downstream helper sees GC units uniformly.

Every length-bearing field in `shared/IR/*.py` is enumerated below. When a
new position/translation field is added to the IR, add it here too — the
companion test `tests/test_compose_scale.py::test_every_length_field_is_scaled`
will fail if it's missed.

Rotations (Euler / quaternion radians), UV coords, colors, vertex weights,
influence floats, curve tensions, and dimensionless ratios are intentionally
untouched.
"""
from __future__ import annotations

try:
    from .....shared.helpers.scale import METERS_TO_GC
    from .....shared.IR.animation import IRKeyframe
except (ImportError, SystemError):
    from shared.helpers.scale import METERS_TO_GC
    from shared.IR.animation import IRKeyframe


def scale_scene_to_gc_units(scene, factor=None):
    """Scale every length field on `scene` in place.

    Args:
        scene: IRScene.
        factor: Scaling factor. Defaults to METERS_TO_GC. Expose as a
            parameter so a test can do a round-trip by scaling once with
            METERS_TO_GC and then with its reciprocal.
    """
    if factor is None:
        factor = METERS_TO_GC
    for model in scene.models:
        _scale_model(model, factor)
    for camera in scene.cameras or []:
        _scale_camera(camera, factor)
    for light in scene.lights or []:
        _scale_light(light, factor)


# ---------------------------------------------------------------------------
# Per-type scalers — one function per IR class that owns length fields.
# ---------------------------------------------------------------------------

def _scale_model(model, f):
    for bone in model.bones:
        _scale_bone(bone, f)
    for mesh in model.meshes:
        _scale_mesh(mesh, f)
    for anim_set in model.bone_animations or []:
        for track in anim_set.tracks or []:
            _scale_bone_track(track, f)
    for shape_set in model.shape_animations or []:
        for track in shape_set.tracks or []:
            # Morph weights are dimensionless — no scaling needed for the
            # blend weight channel itself. The target vertex_positions are
            # scaled via their owning IRShapeKey below.
            pass
    # IRShapeKey vertex positions live on the IRMesh via its shape_keys
    # attribute if present; the mesh scaler handles those.
    for c in model.limit_location_constraints or []:
        _scale_limit_constraint(c, f)
    for c in model.ik_constraints or []:
        _scale_ik_constraint(c, f)
    # Rotation / track / copy-location / copy-rotation constraints carry no
    # distances (only bone names, axes, radian values) — nothing to scale.


def _scale_bone(bone, f):
    bone.position = tuple(c * f for c in bone.position)
    # `world_matrix` / `normalized_world_matrix` (and the local pair) can
    # legitimately share one list object — they're identical whenever the
    # source skeleton has no scale-correction step. Dedup by identity so
    # we never scale the same list twice.
    seen = set()
    for attr in ('world_matrix', 'local_matrix',
                 'normalized_world_matrix', 'normalized_local_matrix',
                 'inverse_bind_matrix'):
        mat = getattr(bone, attr, None)
        if mat is None:
            continue
        if id(mat) in seen:
            continue
        seen.add(id(mat))
        # For IBM: M^-1 = [R^-1 | -R^-1·T]. Scaling the coordinate system
        # by `f` scales the inverse's translation in the same direction
        # as M, so the simple translation-column scale is correct for
        # both M and M^-1.
        _scale_matrix_translation(mat, f)
    # scale_correction is a pure rotation/scale matrix — no translation.


def _scale_mesh(mesh, f):
    mesh.vertices = [tuple(c * f for c in v) for v in mesh.vertices]
    if getattr(mesh, 'local_matrix', None) is not None:
        _scale_matrix_translation(mesh.local_matrix, f)
    if getattr(mesh, 'deformed_vertices', None) is not None:
        mesh.deformed_vertices = [tuple(c * f for c in v)
                                  for v in mesh.deformed_vertices]
    for sk in getattr(mesh, 'shape_keys', None) or []:
        sk.vertex_positions = [tuple(c * f for c in v)
                               for v in sk.vertex_positions]


def _scale_bone_track(track, f):
    # Only location channels get scaled — rotation (radians) and scale
    # (dimensionless ratios) are untouched.
    track.location = [[_scale_kf(kf, f) for kf in channel]
                      for channel in track.location]
    if getattr(track, 'rest_local_matrix', None) is not None:
        _scale_matrix_translation(track.rest_local_matrix, f)
    track.rest_position = tuple(c * f for c in track.rest_position)
    if getattr(track, 'spline_path', None) is not None:
        sp = track.spline_path
        sp.control_points = [[c * f for c in p] for p in sp.control_points]
        if sp.world_matrix is not None:
            _scale_matrix_translation(sp.world_matrix, f)
        # Spline parameter keyframes are curve-parameter values (0..1
        # typically), not distances — do not scale.


def _scale_camera(camera, f):
    if camera.position is not None:
        camera.position = tuple(c * f for c in camera.position)
    if camera.target_position is not None:
        camera.target_position = tuple(c * f for c in camera.target_position)
    camera.near *= f
    camera.far *= f
    # fov is an angle (degrees); roll is radians; aspect is a ratio — none scale.
    for anim in camera.animations or []:
        _scale_camera_keyframes(anim, f)


def _scale_camera_keyframes(anim, f):
    for attr in ('eye_x', 'eye_y', 'eye_z',
                 'target_x', 'target_y', 'target_z',
                 'near', 'far'):
        kfs = getattr(anim, attr, None)
        if kfs:
            setattr(anim, attr, [_scale_kf(kf, f) for kf in kfs])
    # roll (radians) and fov (degrees) are not scaled.


def _scale_light(light, f):
    if light.position is not None:
        light.position = tuple(c * f for c in light.position)
    if light.target_position is not None:
        light.target_position = tuple(c * f for c in light.target_position)


def _scale_limit_constraint(c, f):
    for attr in ('min_x', 'max_x', 'min_y', 'max_y', 'min_z', 'max_z'):
        v = getattr(c, attr, None)
        if v is not None:
            setattr(c, attr, v * f)


def _scale_ik_constraint(c, f):
    for bp in c.bone_repositions or []:
        bp.bone_length *= f
    # pole_angle is radians — do not scale.


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def _scale_matrix_translation(mat, f):
    """Scale the translation column of a 4x4 matrix (mat[0..2][3]) in place."""
    for row in range(3):
        mat[row][3] *= f


def _scale_kf(kf, f):
    """Scale an IRKeyframe's value and tangent handles/slopes.

    Returns a new IRKeyframe — IRKeyframe is a dataclass and may be shared
    (e.g. the same keyframe list attached to multiple owners), so mutating
    it in place could double-scale on a second pass.
    """
    return IRKeyframe(
        frame=kf.frame,
        value=kf.value * f,
        interpolation=kf.interpolation,
        handle_left=((kf.handle_left[0], kf.handle_left[1] * f)
                     if kf.handle_left is not None else None),
        handle_right=((kf.handle_right[0], kf.handle_right[1] * f)
                      if kf.handle_right is not None else None),
        slope_in=kf.slope_in * f if kf.slope_in is not None else None,
        slope_out=kf.slope_out * f if kf.slope_out is not None else None,
    )
