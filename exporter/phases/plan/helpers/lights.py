"""Plan BRLight list into IRLight list.

Pure — no bpy. Converts linear RGB to sRGB and Blender Z-up positions
to GameCube Y-up: Blender (x, y, z) → GC (x, z, -y).
"""
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


def plan_lights(br_lights, logger=StubLogger()):
    """Convert BR lights (Blender frame) into IR lights (GC frame)."""
    out = []
    for br in br_lights:
        color = (
            linear_to_srgb(br.color[0]),
            linear_to_srgb(br.color[1]),
            linear_to_srgb(br.color[2]),
        )

        if br.is_ambient:
            out.append(IRLight(name=br.name, type=LightType.AMBIENT, color=color))
            continue

        ir_type = _BLENDER_TYPE_TO_IR.get(br.blender_type)
        if ir_type is None:
            continue

        out.append(IRLight(
            name=br.name,
            type=ir_type,
            color=color,
            position=_zup_to_yup(br.location),
            target_position=_zup_to_yup(br.target_location),
            brightness=br.energy,
        ))
    return out


def _zup_to_yup(p):
    if p is None:
        return None
    return (p[0], p[2], -p[1])
