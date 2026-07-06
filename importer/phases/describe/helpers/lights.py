"""Describe Light nodes into IRLight dataclasses."""
try:
    from .....shared.Constants.hsd import (
        LOBJ_TYPE_MASK, LOBJ_AMBIENT, LOBJ_INFINITE, LOBJ_POINT, LOBJ_SPOT,
        HSD_A_L_LITC_R, HSD_A_L_LITC_G, HSD_A_L_LITC_B, HSD_A_L_LITC_A,
        HSD_A_L_VIS, HSD_A_L_CUTOFF,
        HSD_A_W_TRAX, HSD_A_W_TRAY, HSD_A_W_TRAZ,
        AOBJ_ANIM_LOOP,
    )
    from .....shared.IR.lights import IRLight, IRLightKeyframes
    from .....shared.IR.enums import LightType
    from .....shared.helpers.logger import StubLogger
    from .....shared.helpers.scale import GC_TO_METERS
    from .keyframe_decoder import decode_fobjdesc
except (ImportError, SystemError):
    from shared.Constants.hsd import (
        LOBJ_TYPE_MASK, LOBJ_AMBIENT, LOBJ_INFINITE, LOBJ_POINT, LOBJ_SPOT,
        HSD_A_L_LITC_R, HSD_A_L_LITC_G, HSD_A_L_LITC_B, HSD_A_L_LITC_A,
        HSD_A_L_VIS, HSD_A_L_CUTOFF,
        HSD_A_W_TRAX, HSD_A_W_TRAY, HSD_A_W_TRAZ,
        AOBJ_ANIM_LOOP,
    )
    from shared.IR.lights import IRLight, IRLightKeyframes
    from shared.IR.enums import LightType
    from shared.helpers.logger import StubLogger
    from shared.helpers.scale import GC_TO_METERS
    from importer.phases.describe.helpers.keyframe_decoder import decode_fobjdesc

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


# LObj AOBJ track type → IRLightKeyframes field name
_LOBJ_TRACK_MAP = {
    HSD_A_L_LITC_R: 'color_r',
    HSD_A_L_LITC_G: 'color_g',
    HSD_A_L_LITC_B: 'color_b',
    HSD_A_L_LITC_A: 'color_a',
    HSD_A_L_VIS: 'visibility',
    HSD_A_L_CUTOFF: 'cutoff',
}

# WObj AOBJ track type → eye / target field name
_WOBJ_EYE_MAP = {
    HSD_A_W_TRAX: 'eye_x',
    HSD_A_W_TRAY: 'eye_y',
    HSD_A_W_TRAZ: 'eye_z',
}

_WOBJ_TARGET_MAP = {
    HSD_A_W_TRAX: 'target_x',
    HSD_A_W_TRAY: 'target_y',
    HSD_A_W_TRAZ: 'target_z',
}

# Fields whose values are positions/distances and must be scaled to meters.
_POSITION_FIELDS = {'eye_x', 'eye_y', 'eye_z', 'target_x', 'target_y', 'target_z'}


def describe_light_animations(light_set, light_index=0, logger=None, options=None):
    """Decode a LightSet's LightAnimation nodes into IRLightKeyframes.

    In: light_set (LightSet, parsed, with .animations); light_index (int, for naming); logger; options.
    Out: list[IRLightKeyframes], one per LightAnimation node present (even a
         track-less one — its presence is scene structure, mirroring cameras).
    """
    if logger is None:
        logger = StubLogger()

    animations = getattr(light_set, 'animations', None)
    if not animations:
        return []

    # LightSet.animations is a null-terminated pointer array, but each
    # LightAnimation also has a `.next` sibling pointer. Flatten both so a
    # chain expressed either way is captured once.
    flat = []
    seen = set()
    for entry in animations:
        node = entry
        while node is not None and id(node) not in seen:
            seen.add(id(node))
            flat.append(node)
            node = getattr(node, 'next', None)

    results = []
    for i, light_anim in enumerate(flat):
        name = 'LightAnim_%d_%02d' % (light_index, i)
        tracks = {}
        end_frame = 0.0
        loop = False

        aobj = getattr(light_anim, 'animation', None)
        if aobj:
            end_frame = getattr(aobj, 'end_frame', 0.0) or 0.0
            loop = bool((getattr(aobj, 'flags', 0) or 0) & AOBJ_ANIM_LOOP)
            _decode_aobj_tracks(aobj, _LOBJ_TRACK_MAP, tracks, logger, options)

        eye_wobj_anim = getattr(light_anim, 'eye_position_animation', None)
        if eye_wobj_anim:
            eye_aobj = getattr(eye_wobj_anim, 'animation', None)
            if eye_aobj:
                if end_frame == 0.0:
                    end_frame = getattr(eye_aobj, 'end_frame', 0.0) or 0.0
                _decode_aobj_tracks(eye_aobj, _WOBJ_EYE_MAP, tracks, logger, options)

        interest_wobj_anim = getattr(light_anim, 'interest_animation', None)
        if interest_wobj_anim:
            interest_aobj = getattr(interest_wobj_anim, 'animation', None)
            if interest_aobj:
                if end_frame == 0.0:
                    end_frame = getattr(interest_aobj, 'end_frame', 0.0) or 0.0
                _decode_aobj_tracks(interest_aobj, _WOBJ_TARGET_MAP, tracks, logger, options)

        results.append(IRLightKeyframes(name=name, end_frame=end_frame, loop=loop, **tracks))
        logger.debug("  Light animation '%s': %d tracks, end_frame=%.1f, loop=%s",
                     name, len(tracks), end_frame, loop)

    return results


def _decode_aobj_tracks(aobj, track_map, tracks, logger, options=None):
    """Walk an AOBJ's Frame chain, decoding each known track into `tracks`.

    Position/distance fields are scaled to meters. Mutates `tracks` in place.
    """
    fobj = getattr(aobj, 'frame', None)
    while fobj:
        field_name = track_map.get(getattr(fobj, 'type', None))
        if field_name is not None:
            keyframes = decode_fobjdesc(fobj, bias=0, scale=1.0, logger=logger, options=options)
            if keyframes:
                if field_name in _POSITION_FIELDS:
                    for kf in keyframes:
                        kf.value *= GC_TO_METERS
                        if kf.handle_left is not None:
                            kf.handle_left = (kf.handle_left[0], kf.handle_left[1] * GC_TO_METERS)
                        if kf.handle_right is not None:
                            kf.handle_right = (kf.handle_right[0], kf.handle_right[1] * GC_TO_METERS)
                        if kf.slope_in is not None:
                            kf.slope_in *= GC_TO_METERS
                        if kf.slope_out is not None:
                            kf.slope_out *= GC_TO_METERS
                tracks[field_name] = keyframes
        fobj = getattr(fobj, 'next', None)
