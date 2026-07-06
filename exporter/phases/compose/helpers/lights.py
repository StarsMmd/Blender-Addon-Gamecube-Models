"""Compose IRLight list into LightSet node trees.

Builds Light nodes with WObject position/interest, type-specific
property nodes (PointLight, SpotLight, or float for infinite),
and wraps them in a LightSet.
"""
try:
    from .....shared.Nodes.Classes.Light.Light import Light
    from .....shared.Nodes.Classes.Light.LightSet import LightSet
    from .....shared.Nodes.Classes.Light.LightAnimation import LightAnimation
    from .....shared.Nodes.Classes.Light.PointLight import PointLight
    from .....shared.Nodes.Classes.Light.SpotLight import SpotLight
    from .....shared.Nodes.Classes.Rendering.WObject import WObject
    from .....shared.Nodes.Classes.Rendering.WObjectAnimation import WObjectAnimation
    from .....shared.Nodes.Classes.Animation.Animation import Animation
    from .....shared.Nodes.Classes.Colors.RGBAColor import RGBAColor
    from .....shared.Constants.hsd import (
        LOBJ_INFINITE, LOBJ_POINT, LOBJ_SPOT,
        LOBJ_DIFFUSE, LOBJ_SPECULAR,
        HSD_A_L_LITC_R, HSD_A_L_LITC_G, HSD_A_L_LITC_B, HSD_A_L_LITC_A,
        HSD_A_L_VIS, HSD_A_L_CUTOFF,
        HSD_A_W_TRAX, HSD_A_W_TRAY, HSD_A_W_TRAZ,
        AOBJ_ANIM_LOOP,
    )
    from .....shared.IR.enums import LightType
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Light.Light import Light
    from shared.Nodes.Classes.Light.LightSet import LightSet
    from shared.Nodes.Classes.Light.LightAnimation import LightAnimation
    from shared.Nodes.Classes.Light.PointLight import PointLight
    from shared.Nodes.Classes.Light.SpotLight import SpotLight
    from shared.Nodes.Classes.Rendering.WObject import WObject
    from shared.Nodes.Classes.Rendering.WObjectAnimation import WObjectAnimation
    from shared.Nodes.Classes.Animation.Animation import Animation
    from shared.Nodes.Classes.Colors.RGBAColor import RGBAColor
    from shared.Constants.hsd import (
        LOBJ_INFINITE, LOBJ_POINT, LOBJ_SPOT,
        LOBJ_DIFFUSE, LOBJ_SPECULAR,
        HSD_A_L_LITC_R, HSD_A_L_LITC_G, HSD_A_L_LITC_B, HSD_A_L_LITC_A,
        HSD_A_L_VIS, HSD_A_L_CUTOFF,
        HSD_A_W_TRAX, HSD_A_W_TRAY, HSD_A_W_TRAZ,
        AOBJ_ANIM_LOOP,
    )
    from shared.IR.enums import LightType
    from shared.helpers.logger import StubLogger

# Reuse the keyframe frame-chain encoders from camera composition.
from .cameras import _build_frame_chain, _build_wobject_animation


_TYPE_TO_FLAG = {
    LightType.SUN: LOBJ_INFINITE,
    LightType.POINT: LOBJ_POINT,
    LightType.SPOT: LOBJ_SPOT,
}


def compose_lights(ir_lights, logger=StubLogger()):
    """Convert IRLight list into LightSet nodes (one per light).

    Sorts ambient lights first (LightSet[0]) to match the convention
    from all tested Colo/XD models.

    Args:
        ir_lights: list[IRLight] from the IR.
        logger: Logger instance.

    Returns:
        list[LightSet] or None if no lights.
    """
    if not ir_lights:
        return None

    # Sort: ambient lights first, then others in original order
    sorted_lights = sorted(ir_lights, key=lambda l: (0 if l.type == LightType.AMBIENT else 1))

    light_sets = []
    for ir_light in sorted_lights:
        light_node = _compose_light(ir_light, logger)
        if light_node is not None:
            light_set = LightSet(address=None, blender_obj=None)
            light_set.light = light_node
            light_set.animations = _compose_light_animations(
                getattr(ir_light, 'animations', None), logger)
            light_sets.append(light_set)

    if not light_sets:
        return None

    logger.info("    Composed %d light(s) in %d LightSet(s)", len(light_sets), len(light_sets))
    return light_sets


def _compose_light_animations(animations, logger):
    """Encode an IRLightKeyframes list into a LightAnimation pointer array.

    Mirrors the LightSet.animations layout: each clip becomes one
    LightAnimation node (sibling `next` left null, matching the null-
    terminated array form the parser reads). A track-less clip round-trips
    an empty-but-present LightAnimation.

    Returns list[LightAnimation] or None if empty.
    """
    if not animations:
        return None

    nodes = [_compose_single_light_animation(a, logger) for a in animations]
    return nodes if nodes else None


def _compose_single_light_animation(anim, logger):
    """Encode one IRLightKeyframes into a LightAnimation node.

    The LObj AOBJ carries colour (LITC_*), visibility, and cutoff tracks;
    eye/target position tracks go into the WObjectAnimations. Values are
    already in GC units by compose time.
    """
    light_anim = LightAnimation(address=None, blender_obj=None)
    light_anim.next = None

    lobj_channels = [
        (anim.color_r, HSD_A_L_LITC_R),
        (anim.color_g, HSD_A_L_LITC_G),
        (anim.color_b, HSD_A_L_LITC_B),
        (anim.color_a, HSD_A_L_LITC_A),
        (anim.visibility, HSD_A_L_VIS),
        (anim.cutoff, HSD_A_L_CUTOFF),
    ]
    lobj_frames = _build_frame_chain(lobj_channels)
    if lobj_frames:
        aobj = Animation(address=None, blender_obj=None)
        aobj.flags = AOBJ_ANIM_LOOP if anim.loop else 0
        aobj.end_frame = float(anim.end_frame)
        aobj.frame = lobj_frames
        aobj.joint = None
        light_anim.animation = aobj
    else:
        light_anim.animation = None

    eye_channels = [
        (anim.eye_x, HSD_A_W_TRAX),
        (anim.eye_y, HSD_A_W_TRAY),
        (anim.eye_z, HSD_A_W_TRAZ),
    ]
    light_anim.eye_position_animation = _build_wobject_animation(
        eye_channels, anim.end_frame, anim.loop)

    target_channels = [
        (anim.target_x, HSD_A_W_TRAX),
        (anim.target_y, HSD_A_W_TRAY),
        (anim.target_z, HSD_A_W_TRAZ),
    ]
    light_anim.interest_animation = _build_wobject_animation(
        target_channels, anim.end_frame, anim.loop)

    logger.debug("    Composed light animation '%s'", anim.name)
    return light_anim


def _compose_light(ir_light, logger):
    """Build a Light node from an IRLight."""
    light = Light(address=None, blender_obj=None)
    light.name = None
    light.link = None

    # Color: IR stores sRGB 0-1, Light node stores 0-255 RGBA
    r = int(ir_light.color[0] * 255 + 0.5)
    g = int(ir_light.color[1] * 255 + 0.5)
    b = int(ir_light.color[2] * 255 + 0.5)

    if ir_light.type == LightType.AMBIENT:
        # Ambient: LOBJ_DIFFUSE only (0x4), no type bits, no position
        light.flags = LOBJ_DIFFUSE
        light.attn_flags = 0
        light.color = _make_rgba(r, g, b, 0)
        light.position = None
        light.interest = None
        light.property = None
        return light

    # Non-ambient: type + diffuse + specular
    type_flag = _TYPE_TO_FLAG.get(ir_light.type, LOBJ_INFINITE)
    light.flags = type_flag | LOBJ_DIFFUSE | LOBJ_SPECULAR
    light.attn_flags = 0
    light.color = _make_rgba(r, g, b, 0)

    # Position
    light.position = _make_wobject(ir_light.position)

    # Interest (target position for spotlights — None if no target)
    light.interest = _make_wobject(ir_light.target_position) if ir_light.target_position else None

    # Type-specific property
    if ir_light.type == LightType.SUN:
        light.property = ir_light.brightness
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
    """Create a WObject with a position vec3.

    IRLight positions are already in GC units by the time compose runs
    (see `scale.py:scale_scene_to_gc_units`), so no local scaling is needed.
    """
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
