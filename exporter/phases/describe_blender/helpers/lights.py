"""Describe Blender light objects as IRLight dataclasses.

Reads light objects from the Blender scene and produces IRLight list.
Handles SUN, POINT, and SPOT light types.
"""
import bpy

try:
    from .....shared.IR.lights import IRLight
    from .....shared.IR.enums import LightType
    from .....shared.helpers.srgb import linear_to_srgb
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.lights import IRLight
    from shared.IR.enums import LightType
    from shared.helpers.srgb import linear_to_srgb
    from shared.helpers.logger import StubLogger


_BLENDER_TYPE_TO_IR = {
    'SUN': LightType.SUN,
    'POINT': LightType.POINT,
    'SPOT': LightType.SPOT,
}


def describe_lights(context, logger=StubLogger()):
    """Read Blender light objects and produce IRLight list.

    Args:
        context: Blender context with active scene.
        logger: Logger instance.

    Returns:
        list[IRLight]
    """
    lights = []

    for obj in bpy.data.objects:
        if obj.type != 'LIGHT':
            continue

        ir_type = _BLENDER_TYPE_TO_IR.get(obj.data.type)
        if ir_type is None:
            logger.debug("  Skipping light '%s': unsupported type '%s'", obj.name, obj.data.type)
            continue

        # Color: Blender stores linear, IR stores sRGB
        c = obj.data.color
        color = (linear_to_srgb(c[0]), linear_to_srgb(c[1]), linear_to_srgb(c[2]))

        # Position: the importer places lights at their GC Y-up positions
        # directly (the coordinate rotations cancel out in the build phase),
        # so obj.location is already in GC space.
        pos = obj.location
        position = (pos.x, pos.y, pos.z)

        # Target position from TRACK_TO constraint
        target_position = None
        for constraint in obj.constraints:
            if constraint.type == 'TRACK_TO' and constraint.target:
                target_loc = constraint.target.location
                target_position = (target_loc.x, target_loc.y, target_loc.z)
                break

        ir_light = IRLight(
            name=obj.name,
            type=ir_type,
            color=color,
            position=position,
            target_position=target_position,
        )
        lights.append(ir_light)

    if lights:
        logger.info("  Described %d light(s)", len(lights))
    return lights
