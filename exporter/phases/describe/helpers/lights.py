"""Snapshot Blender lights into BRLight dataclasses.

Blender→BR only: keeps colours in linear RGB and positions in Z-up
Blender frame. The sRGB conversion and Y-up coordinate flip happen in
``plan/helpers/lights.py`` on the way to IR. Light animation clips are read
back from real fcurves (an Action on the light object + a paired Action on
its TRACK_TO target empty), mirroring the camera path.
"""
import bpy

try:
    from .....shared.BR.lights import BRLight, BRLightAnimation
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.BR.lights import BRLight, BRLightAnimation
    from shared.helpers.logger import StubLogger

from .cameras import _extract_fcurve


def describe_lights(context, logger=StubLogger()):
    """Read Blender light objects into a BRLight list.

    In: context (bpy.types.Context); logger.
    Out: list[BRLight].
    """
    out = []

    for obj in bpy.data.objects:
        if obj.type != 'LIGHT':
            continue
        if obj.hide_viewport or obj.hide_get():
            logger.debug("  Skipping light '%s': hidden", obj.name)
            continue

        c = obj.data.color
        color = (c[0], c[1], c[2])  # linear; plan converts to sRGB

        target_obj = _track_to_target(obj)

        # Ambient marker: explicit dat_light_type custom prop. Ambient
        # lights have no Blender equivalent — they're tagged on the
        # Blender side and resurrected as zero-energy POINT lights with
        # is_ambient=True.
        if obj.get('dat_light_type') == 'AMBIENT':
            out.append(BRLight(
                name=obj.name,
                blender_type='POINT',
                color=color,
                energy=0.0,
                is_ambient=True,
                animations=_describe_light_animations(obj, target_obj),
            ))
            continue

        if obj.data.type not in ('SUN', 'POINT', 'SPOT'):
            logger.debug("  Skipping light '%s': unsupported type '%s'", obj.name, obj.data.type)
            continue

        loc = obj.location
        location = (loc.x, loc.y, loc.z)
        target_location = None
        if target_obj is not None:
            t = target_obj.location
            target_location = (t.x, t.y, t.z)

        # SUN with no TRACK_TO: derive direction from the light's forward
        # axis (object's −Z vector). Plan converts to IR position+target.
        if obj.data.type == 'SUN' and target_location is None:
            from mathutils import Vector
            forward = obj.matrix_world.to_quaternion() @ Vector((0, 0, -1))
            location = (0.0, 0.0, 0.0)
            target_location = (forward.x, forward.y, forward.z)

        out.append(BRLight(
            name=obj.name,
            blender_type=obj.data.type,
            color=color,
            energy=obj.data.energy,
            location=location,
            target_location=target_location,
            is_ambient=False,
            animations=_describe_light_animations(obj, target_obj),
        ))

    if out:
        logger.info("  Described %d light(s)", len(out))
    return out


def _describe_light_animations(lamp, target_obj):
    """Recover BRLightAnimation clips from a light's fcurves (or []).

    Reads the light object's Action (colour/energy/cutoff/eye) and the
    target empty's Action (interest). A light with no assigned Action — or
    an inert empty clip that built no fcurves — yields no clip.
    """
    anim_data = lamp.animation_data
    if not anim_data or not anim_data.action:
        return []
    action = anim_data.action

    tracks = {
        'color_r': _extract_fcurve(action, 'data.color', 0),
        'color_g': _extract_fcurve(action, 'data.color', 1),
        'color_b': _extract_fcurve(action, 'data.color', 2),
        'color_a': [],
        'visibility': _extract_fcurve(action, 'data.energy', 0),
        'cutoff': _extract_fcurve(action, 'data.spot_size', 0),
        'loc_x': _extract_fcurve(action, 'location', 0),
        'loc_y': _extract_fcurve(action, 'location', 1),
        'loc_z': _extract_fcurve(action, 'location', 2),
        'target_loc_x': [],
        'target_loc_y': [],
        'target_loc_z': [],
    }
    if target_obj and target_obj.animation_data and target_obj.animation_data.action:
        ta = target_obj.animation_data.action
        tracks['target_loc_x'] = _extract_fcurve(ta, 'location', 0)
        tracks['target_loc_y'] = _extract_fcurve(ta, 'location', 1)
        tracks['target_loc_z'] = _extract_fcurve(ta, 'location', 2)

    if not any(tracks.values()):
        return []

    end_frame = 0.0
    for keyframes in tracks.values():
        if keyframes:
            end_frame = max(end_frame, max(kf.frame for kf in keyframes))

    return [BRLightAnimation(name=action.name, end_frame=end_frame, loop=False, **tracks)]


def _track_to_target(obj):
    for constraint in obj.constraints:
        if constraint.type == 'TRACK_TO' and constraint.target:
            return constraint.target
    return None
