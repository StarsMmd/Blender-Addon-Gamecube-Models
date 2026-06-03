"""Describe Camera nodes into IRCamera dataclasses."""
try:
    from .....shared.Constants.hsd import (
        COBJ_PROJECTION_PERSPECTIVE, COBJ_PROJECTION_FRUSTUM, COBJ_PROJECTION_ORTHO,
        HSD_A_C_EYEX, HSD_A_C_EYEY, HSD_A_C_EYEZ,
        HSD_A_C_ATX, HSD_A_C_ATY, HSD_A_C_ATZ,
        HSD_A_C_ROLL, HSD_A_C_FOVY, HSD_A_C_NEAR, HSD_A_C_FAR,
        HSD_A_W_TRAX, HSD_A_W_TRAY, HSD_A_W_TRAZ,
        AOBJ_ANIM_LOOP,
    )
    from .....shared.IR.camera import IRCamera, IRCameraKeyframes
    from .....shared.IR.enums import CameraProjection
    from .....shared.helpers.logger import StubLogger
    from .....shared.helpers.scale import GC_TO_METERS
    from .keyframe_decoder import decode_fobjdesc
except (ImportError, SystemError):
    from shared.Constants.hsd import (
        COBJ_PROJECTION_PERSPECTIVE, COBJ_PROJECTION_FRUSTUM, COBJ_PROJECTION_ORTHO,
        HSD_A_C_EYEX, HSD_A_C_EYEY, HSD_A_C_EYEZ,
        HSD_A_C_ATX, HSD_A_C_ATY, HSD_A_C_ATZ,
        HSD_A_C_ROLL, HSD_A_C_FOVY, HSD_A_C_NEAR, HSD_A_C_FAR,
        HSD_A_W_TRAX, HSD_A_W_TRAY, HSD_A_W_TRAZ,
        AOBJ_ANIM_LOOP,
    )
    from shared.IR.camera import IRCamera, IRCameraKeyframes
    from shared.IR.enums import CameraProjection
    from shared.helpers.logger import StubLogger
    from shared.helpers.scale import GC_TO_METERS
    from importer.phases.describe.helpers.keyframe_decoder import decode_fobjdesc

_PROJECTION_MAP = {
    COBJ_PROJECTION_PERSPECTIVE: CameraProjection.PERSPECTIVE,
    COBJ_PROJECTION_FRUSTUM: CameraProjection.PERSPECTIVE,
    COBJ_PROJECTION_ORTHO: CameraProjection.ORTHO,
}

# CObj AOBJ track type → IRCameraKeyframes field name
_COBJ_TRACK_MAP = {
    HSD_A_C_EYEX: 'eye_x',
    HSD_A_C_EYEY: 'eye_y',
    HSD_A_C_EYEZ: 'eye_z',
    HSD_A_C_ATX: 'target_x',
    HSD_A_C_ATY: 'target_y',
    HSD_A_C_ATZ: 'target_z',
    HSD_A_C_ROLL: 'roll',
    HSD_A_C_FOVY: 'fov',
    HSD_A_C_NEAR: 'near',
    HSD_A_C_FAR: 'far',
}

# WObj AOBJ track type → (IRCameraKeyframes field name for eye or target)
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


def describe_camera(camera_node, camera_index=0, options=None, logger=None):
    """Convert a parsed Camera node to an IRCamera with positions in meters.

    In: camera_node (Camera, parsed); camera_index (int, ≥0, used for naming); options (dict|None); logger (Logger|None).
    Out: IRCamera with projection/position/target/fov/near/far set; None if projection unrecognized.
    """
    if options is None:
        options = {}
    if logger is None:
        logger = StubLogger()
    projection = _PROJECTION_MAP.get(camera_node.perspective_flags)
    if projection is None:
        logger.leniency("camera_unknown_projection",
                        "Camera %d perspective_flags=0x%X not in {PERSPECTIVE=1, FRUSTUM=2, ORTHO=3}",
                        camera_index, camera_node.perspective_flags)
        return None

    # XD/Colosseum ignore the PKX camera in every real game context (battles,
    # summary screen, PC box, overworld) — both disassemblies only read
    # scene_data cameras out of floor/waza/effect archives, never out of a
    # Pokémon model PKX. Name it "Debug_Camera" to reflect that it's most
    # likely a SysDolphin-era debug/preview camera preserved by the format.
    name = 'Debug_Camera' if camera_index == 0 else 'Camera_%d' % camera_index

    position = None
    if camera_node.position and hasattr(camera_node.position, 'position'):
        position = tuple(p * GC_TO_METERS for p in camera_node.position.position)

    target_position = None
    if camera_node.interest and hasattr(camera_node.interest, 'position') and camera_node.interest.position:
        target_position = tuple(p * GC_TO_METERS for p in camera_node.interest.position)

    if position is None or target_position is None:
        missing = []
        if position is None:
            missing.append("eye")
        if target_position is None:
            missing.append("target")
        logger.leniency("camera_missing_eye_or_target",
                        "Camera %d missing %s; game's C_MTXLookAt requires both",
                        camera_index, "+".join(missing))

    if abs(camera_node.near) < 1e-6 or camera_node.far <= camera_node.near:
        logger.leniency("camera_degenerate_near_far",
                        "Camera %d has degenerate near/far (near=%.4f, far=%.4f)",
                        camera_index, camera_node.near, camera_node.far)

    return IRCamera(
        name=name,
        projection=projection,
        position=position,
        target_position=target_position,
        roll=camera_node.roll,
        near=camera_node.near * GC_TO_METERS,
        far=camera_node.far * GC_TO_METERS,
        field_of_view=camera_node.field_of_view,
        aspect=camera_node.aspect,
    )


def describe_camera_animations(camera_set, camera_index=0, logger=StubLogger(), options=None):
    """Decode CameraAnimation nodes from a CameraSet into IRCameraKeyframes.

    In: camera_set (CameraSet, parsed, with .animations); camera_index (int, ≥0, for naming); logger (Logger); options (dict|None).
    Out: list[IRCameraKeyframes], one per CameraAnimation that produced any tracks (positions in meters).
    """
    animations = getattr(camera_set, 'animations', None)
    if not animations:
        return []

    results = []
    for i, cam_anim in enumerate(animations):
        name = 'CamAnim_%d_%02d' % (camera_index, i)
        tracks = {}
        end_frame = 0.0
        loop = False

        # Decode CObj's own AOBJ (FOV, roll, near, far, and possibly eye/target)
        aobj = getattr(cam_anim, 'animation', None)
        if aobj:
            end_frame = getattr(aobj, 'end_frame', 0.0) or 0.0
            flags = getattr(aobj, 'flags', 0) or 0
            loop = bool(flags & AOBJ_ANIM_LOOP)
            _decode_aobj_tracks(aobj, _COBJ_TRACK_MAP, tracks, logger, options)

        # Decode eye WObjectAnimation's AOBJ
        eye_wobj_anim = getattr(cam_anim, 'eye_position_animation', None)
        if eye_wobj_anim:
            eye_aobj = getattr(eye_wobj_anim, 'animation', None)
            if eye_aobj:
                # Use eye AOBJ's end_frame if the main AOBJ was missing
                if end_frame == 0.0:
                    end_frame = getattr(eye_aobj, 'end_frame', 0.0) or 0.0
                _decode_aobj_tracks(eye_aobj, _WOBJ_EYE_MAP, tracks, logger, options)

        # Decode interest/target WObjectAnimation's AOBJ
        interest_wobj_anim = getattr(cam_anim, 'interest_animation', None)
        if interest_wobj_anim:
            interest_aobj = getattr(interest_wobj_anim, 'animation', None)
            if interest_aobj:
                if end_frame == 0.0:
                    end_frame = getattr(interest_aobj, 'end_frame', 0.0) or 0.0
                _decode_aobj_tracks(interest_aobj, _WOBJ_TARGET_MAP, tracks, logger, options)

        if tracks:
            ir_kf = IRCameraKeyframes(
                name=name,
                end_frame=end_frame,
                loop=loop,
                **tracks,
            )
            results.append(ir_kf)
            logger.debug("  Camera animation '%s': %d tracks, end_frame=%.1f, loop=%s",
                         name, len(tracks), end_frame, loop)

    return results


_POSITION_FIELDS = {'eye_x', 'eye_y', 'eye_z', 'target_x', 'target_y', 'target_z', 'near', 'far'}


def _decode_aobj_tracks(aobj, track_map, tracks, logger, options=None):
    """Walk an AOBJ's Frame chain and decode each known track into the tracks dict.

    In: aobj (Animation node, .frame linked list); track_map (dict[int,str], fobj.type→field name); tracks (dict[str, list[IRKeyframe]], populated in place; position fields scaled to meters); logger (Logger); options (dict|None).
    Out: None — mutates `tracks` in place.
    """
    fobj = getattr(aobj, 'frame', None)
    while fobj:
        fobj_type = getattr(fobj, 'type', None)
        field_name = track_map.get(fobj_type)
        if field_name is not None:
            keyframes = decode_fobjdesc(fobj, bias=0, scale=1.0, logger=logger, options=options)
            if keyframes:
                # Scale position and distance tracks to meters
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
                logger.debug("    Decoded camera track type %s → %s: %d keyframes",
                             fobj_type, field_name, len(keyframes))
        fobj = getattr(fobj, 'next', None)
