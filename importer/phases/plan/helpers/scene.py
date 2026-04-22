"""Plan helpers for scene-level objects (lights, cameras) and pass-through
wrappers (constraints, particle summaries)."""
import math

try:
    from .....shared.BR.lights import BRLight
    from .....shared.BR.cameras import BRCamera, BRCameraAnimation
    from .....shared.BR.constraints import BRConstraints, BRParticleSummary
    from .....shared.IR.enums import CameraProjection
    from .....shared.helpers.srgb import srgb_to_linear
except (ImportError, SystemError):
    from shared.BR.lights import BRLight
    from shared.BR.cameras import BRCamera, BRCameraAnimation
    from shared.BR.constraints import BRConstraints, BRParticleSummary
    from shared.IR.enums import CameraProjection
    from shared.helpers.srgb import srgb_to_linear


# ---------------------------------------------------------------------------
# Lights
# ---------------------------------------------------------------------------


_LIGHT_TYPE_MAP = {'SUN': 'SUN', 'POINT': 'POINT', 'SPOT': 'SPOT'}


def plan_lights(ir_lights):
    """Convert IRLight list to BRLight list.

    Handles coord rotation (GC Y-up → Blender Z-up: (x, y, z) → (x, -z, y))
    and sRGB → linear color conversion. Ambient IR lights become
    zero-energy POINT lights flagged ``is_ambient=True`` so build can
    stamp the ``dat_light_type`` custom property.
    """
    return [plan_light(ir) for ir in ir_lights]


def plan_light(ir_light):
    color_linear = _linearize_rgb(ir_light.color)
    if ir_light.type.value == 'AMBIENT':
        return BRLight(
            name=ir_light.name,
            blender_type='POINT',
            color=color_linear,
            energy=0.0,
            is_ambient=True,
        )
    return BRLight(
        name=ir_light.name,
        blender_type=_LIGHT_TYPE_MAP.get(ir_light.type.value, 'POINT'),
        color=color_linear,
        energy=ir_light.brightness,
        location=_gc_to_blender(ir_light.position) if ir_light.position else None,
        target_location=(_gc_to_blender(ir_light.target_position)
                         if ir_light.target_position else None),
    )


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------


_SENSOR_HEIGHT = 18.0  # mm — matches the original build-phase constant
_BLENDER_DEFAULT_LENS = 50.0


def plan_cameras(ir_cameras):
    return [plan_camera(ir_cam) for ir_cam in ir_cameras]


def plan_camera(ir_cam):
    """Convert IRCamera → BRCamera.

    FOV (degrees, vertical) → focal-length in mm is computed here so
    build never does math. Ortho cameras store ``field_of_view`` as an
    ortho_scale; we carry that through on the ``lens`` field regardless
    of projection, and the build layer knows which to apply.
    """
    if ir_cam.projection == CameraProjection.ORTHO:
        lens = ir_cam.field_of_view  # used as ortho_scale
    else:
        lens = _fov_to_lens(ir_cam.field_of_view, _SENSOR_HEIGHT)

    return BRCamera(
        name=ir_cam.name,
        projection='ORTHO' if ir_cam.projection == CameraProjection.ORTHO else 'PERSP',
        lens=lens,
        sensor_height=_SENSOR_HEIGHT,
        clip_start=ir_cam.near,
        clip_end=ir_cam.far,
        aspect=ir_cam.aspect,
        location=_gc_to_blender(ir_cam.position) if ir_cam.position else None,
        target_location=(_gc_to_blender(ir_cam.target_position)
                         if ir_cam.target_position else None),
        animations=[_plan_camera_animation(anim) for anim in (ir_cam.animations or [])],
    )


def _plan_camera_animation(anim):
    """Convert IRCameraKeyframes → BRCameraAnimation with values already
    transformed into Blender space (coord flips + FOV→lens conversion)."""
    return BRCameraAnimation(
        name=anim.name,
        loc_x=anim.eye_x,             # unchanged
        loc_y=_negate_keyframes(anim.eye_z),  # GC Z → Blender Y with sign flip
        loc_z=anim.eye_y,             # GC Y → Blender Z (unchanged)
        roll=anim.roll,
        lens=_map_keyframes(anim.fov, lambda v: _fov_to_lens(v, _SENSOR_HEIGHT)),
        clip_start=anim.near,
        clip_end=anim.far,
        target_loc_x=anim.target_x,
        target_loc_y=_negate_keyframes(anim.target_z),
        target_loc_z=anim.target_y,
        end_frame=anim.end_frame,
        loop=anim.loop,
    )


def _map_keyframes(keyframes, transform):
    """Apply a per-value transform while preserving IRKeyframe metadata."""
    if not keyframes:
        return []
    mapped = []
    for kf in keyframes:
        from dataclasses import replace
        mapped.append(replace(kf, value=transform(kf.value)))
    return mapped


def _negate_keyframes(keyframes):
    return _map_keyframes(keyframes or [], lambda v: -v)


def _fov_to_lens(fov_degrees, sensor_height):
    if fov_degrees <= 0 or fov_degrees >= 180:
        return _BLENDER_DEFAULT_LENS
    return sensor_height / (2.0 * math.tan(math.radians(fov_degrees) / 2.0))


# ---------------------------------------------------------------------------
# Constraints (pass-through)
# ---------------------------------------------------------------------------


def plan_constraints(ir_ik, ir_copy_loc, ir_track_to, ir_copy_rot,
                     ir_limit_rot, ir_limit_loc):
    """Wrap IR constraint lists in BRConstraints without modification."""
    return BRConstraints(
        ik=list(ir_ik),
        copy_location=list(ir_copy_loc),
        track_to=list(ir_track_to),
        copy_rotation=list(ir_copy_rot),
        limit_rotation=list(ir_limit_rot),
        limit_location=list(ir_limit_loc),
    )


# ---------------------------------------------------------------------------
# Particles summary
# ---------------------------------------------------------------------------


def plan_particle_summary(ir_particles):
    """Compute the counts that build writes as armature custom props.

    Returns None if there's no particle system; build phase skips entirely.
    """
    if ir_particles is None:
        return None
    return BRParticleSummary(
        generator_count=len(ir_particles.generators),
        texture_count=len(ir_particles.textures),
    )


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------


def _gc_to_blender(xyz):
    """GC Y-up → Blender Z-up: (x, y, z) → (x, -z, y)."""
    x, y, z = xyz
    return (x, -z, y)


def _linearize_rgb(rgb):
    r, g, b = rgb[0], rgb[1], rgb[2]
    return (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b))
