"""Compose IRLight list into LightSet node trees.

Builds Light nodes with WObject position/interest, type-specific
property nodes (PointLight, SpotLight, or float for infinite),
and wraps them in a LightSet.
"""
try:
    from .....shared.Nodes.Classes.Light.Light import Light
    from .....shared.Nodes.Classes.Light.LightSet import LightSet
    from .....shared.Nodes.Classes.Light.PointLight import PointLight
    from .....shared.Nodes.Classes.Light.SpotLight import SpotLight
    from .....shared.Nodes.Classes.Rendering.WObject import WObject
    from .....shared.Nodes.Classes.Colors.RGBAColor import RGBAColor
    from .....shared.Constants.hsd import (
        LOBJ_INFINITE, LOBJ_POINT, LOBJ_SPOT,
        LOBJ_DIFFUSE, LOBJ_SPECULAR,
    )
    from .....shared.IR.enums import LightType
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Light.Light import Light
    from shared.Nodes.Classes.Light.LightSet import LightSet
    from shared.Nodes.Classes.Light.PointLight import PointLight
    from shared.Nodes.Classes.Light.SpotLight import SpotLight
    from shared.Nodes.Classes.Rendering.WObject import WObject
    from shared.Nodes.Classes.Colors.RGBAColor import RGBAColor
    from shared.Constants.hsd import (
        LOBJ_INFINITE, LOBJ_POINT, LOBJ_SPOT,
        LOBJ_DIFFUSE, LOBJ_SPECULAR,
    )
    from shared.IR.enums import LightType
    from shared.helpers.logger import StubLogger


_TYPE_TO_FLAG = {
    LightType.SUN: LOBJ_INFINITE,
    LightType.POINT: LOBJ_POINT,
    LightType.SPOT: LOBJ_SPOT,
}


def compose_lights(ir_lights, logger=StubLogger()):
    """Convert IRLight list into a LightSet node.

    Args:
        ir_lights: list[IRLight] from the IR.
        logger: Logger instance.

    Returns:
        list[LightSet] (single-element) or None if no lights.
    """
    if not ir_lights:
        return None

    light_nodes = []
    for ir_light in ir_lights:
        light_node = _compose_light(ir_light, logger)
        if light_node is not None:
            light_nodes.append(light_node)

    if not light_nodes:
        return None

    # Chain lights via .link
    for i in range(len(light_nodes) - 1):
        light_nodes[i].link = light_nodes[i + 1]

    # Wrap in LightSet
    light_set = LightSet(address=None, blender_obj=None)
    light_set.light = light_nodes[0]
    light_set.animations = []

    logger.info("    Composed %d light(s)", len(light_nodes))
    return [light_set]


def _compose_light(ir_light, logger):
    """Build a Light node from an IRLight."""
    light = Light(address=None, blender_obj=None)
    light.name = None
    light.link = None

    # Flags: type + diffuse + specular (standard for visible lights)
    type_flag = _TYPE_TO_FLAG.get(ir_light.type, LOBJ_INFINITE)
    light.flags = type_flag | LOBJ_DIFFUSE | LOBJ_SPECULAR
    light.attn_flags = 0

    # Color: IR stores sRGB 0-1, Light node stores 0-255 RGBA
    r = int(ir_light.color[0] * 255 + 0.5)
    g = int(ir_light.color[1] * 255 + 0.5)
    b = int(ir_light.color[2] * 255 + 0.5)
    light.color = _make_rgba(r, g, b, 255)

    # Position
    light.position = _make_wobject(ir_light.position)

    # Interest (target position for spotlights)
    light.interest = _make_wobject(ir_light.target_position)

    # Type-specific property
    if ir_light.type == LightType.SUN:
        light.property = 1.0  # Brightness float
    elif ir_light.type == LightType.POINT:
        prop = PointLight(address=None, blender_obj=None)
        prop.reference_br = 1.0
        prop.reference_distance = 100.0
        light.property = prop
    elif ir_light.type == LightType.SPOT:
        prop = SpotLight(address=None, blender_obj=None)
        prop.cutoff = 45.0
        prop.spot_flags = 0
        prop.reference_br = 1.0
        prop.reference_distance = 100.0
        prop.distance_attn_flags = 0
        light.property = prop

    return light


def _make_wobject(position):
    """Create a WObject with a position vec3."""
    wobj = WObject(address=None, blender_obj=None)
    wobj.name = None
    wobj.position = list(position) if position else [0.0, 0.0, 0.0]
    wobj.render = None
    return wobj


def _make_rgba(r, g, b, a):
    """Create an RGBAColor node with the given u8 values."""
    c = RGBAColor(address=None, blender_obj=None)
    c.red = r
    c.green = g
    c.blue = b
    c.alpha = a
    return c
