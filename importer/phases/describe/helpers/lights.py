"""Describe Light nodes into IRLight dataclasses."""
try:
    from .....shared.Constants.hsd import LOBJ_TYPE_MASK, LOBJ_AMBIENT, LOBJ_INFINITE, LOBJ_POINT, LOBJ_SPOT
    from .....shared.IR.lights import IRLight
    from .....shared.IR.enums import LightType
    from .....shared.helpers.scale import GC_TO_METERS
except (ImportError, SystemError):
    from shared.Constants.hsd import LOBJ_TYPE_MASK, LOBJ_AMBIENT, LOBJ_INFINITE, LOBJ_POINT, LOBJ_SPOT
    from shared.IR.lights import IRLight
    from shared.IR.enums import LightType
    from shared.helpers.scale import GC_TO_METERS

_LIGHT_TYPE_MAP = {
    LOBJ_AMBIENT: LightType.AMBIENT,
    LOBJ_INFINITE: LightType.SUN,
    LOBJ_POINT: LightType.POINT,
    LOBJ_SPOT: LightType.SPOT,
}


def describe_light(light_node, light_index=0):
    """Convert a parsed Light node to an IRLight (positions in meters, color [0,1]).

    In: light_node (Light, parsed); light_index (int, ≥0, used in name when light has no name).
    Out: IRLight|None — None if the LObj type is not in {AMBIENT,INFINITE,POINT,SPOT}.
    """
    light_type_flag = light_node.flags & LOBJ_TYPE_MASK
    ir_type = _LIGHT_TYPE_MAP.get(light_type_flag)
    if ir_type is None:
        return None

    name = 'Light_%s' % (light_node.name or str(light_index))

    color = (1.0, 1.0, 1.0)
    if light_node.color:
        color = (light_node.color.red / 255.0,
                 light_node.color.green / 255.0,
                 light_node.color.blue / 255.0)

    position = None
    if light_node.position and hasattr(light_node.position, 'position'):
        position = tuple(p * GC_TO_METERS for p in light_node.position.position)

    target_position = None
    if light_node.interest and hasattr(light_node.interest, 'position') and light_node.interest.position:
        target_position = tuple(p * GC_TO_METERS for p in light_node.interest.position)

    # Extract brightness from property (SUN lights store it as a float)
    brightness = 1.0
    prop = getattr(light_node, 'property', None)
    if isinstance(prop, (int, float)):
        brightness = float(prop)

    return IRLight(
        name=name,
        type=ir_type,
        color=color,
        position=position,
        target_position=target_position,
        brightness=brightness,
    )
