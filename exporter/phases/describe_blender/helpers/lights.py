"""Describe Blender light objects as IRLight dataclasses.

Reads light objects from the Blender scene and produces IRLight list.
Handles AMBIENT, SUN, POINT, and SPOT light types.
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

        if obj.hide_viewport or obj.hide_get():
            logger.debug("  Skipping light '%s': hidden", obj.name)
            continue

        # Check for ambient light marker
        if obj.get('dat_light_type') == 'AMBIENT':
            c = obj.data.color
            color = (linear_to_srgb(c[0]), linear_to_srgb(c[1]), linear_to_srgb(c[2]))
            lights.append(IRLight(
                name=obj.name,
                type=LightType.AMBIENT,
                color=color,
            ))
            continue

        ir_type = _BLENDER_TYPE_TO_IR.get(obj.data.type)
        if ir_type is None:
            logger.debug("  Skipping light '%s': unsupported type '%s'", obj.name, obj.data.type)
            continue

        # Color: Blender stores linear, IR stores sRGB
        c = obj.data.color
        color = (linear_to_srgb(c[0]), linear_to_srgb(c[1]), linear_to_srgb(c[2]))

        # Position: convert Blender Z-up to IR Y-up: (x, y, z) → (x, z, -y)
        pos = obj.location
        position = (pos.x, pos.z, -pos.y)

        # Target position from TRACK_TO constraint
        target_position = None
        for constraint in obj.constraints:
            if constraint.type == 'TRACK_TO' and constraint.target:
                t = constraint.target.location
                target_position = (t.x, t.z, -t.y)
                break

        ir_light = IRLight(
            name=obj.name,
            type=ir_type,
            color=color,
            position=position,
            target_position=target_position,
            brightness=obj.data.energy,
        )
        lights.append(ir_light)

    if lights:
        logger.info("  Described %d light(s)", len(lights))
    return lights
