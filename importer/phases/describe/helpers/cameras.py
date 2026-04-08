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


def describe_camera(camera_node, camera_index=0):
    """Convert a Camera node to IRCamera.

    Args:
        camera_node: Parsed Camera node (from CameraSet or SceneData).
        camera_index: Index for naming.

    Returns:
        IRCamera or None if the projection type is unrecognized.
    """
    projection = _PROJECTION_MAP.get(camera_node.perspective_flags)
    if projection is None:
        return None

    name = 'Battle_Camera' if camera_index == 0 else 'Camera_%d' % camera_index

    position = None
    if camera_node.position and hasattr(camera_node.position, 'position'):
        position = tuple(camera_node.position.position)

    target_position = None
    if camera_node.interest and hasattr(camera_node.interest, 'position') and camera_node.interest.position:
        target_position = tuple(camera_node.interest.position)

    return IRCamera(
        name=name,
        projection=projection,
        position=position,
        target_position=target_position,
        roll=camera_node.roll,
        near=camera_node.near,
        far=camera_node.far,
        field_of_view=camera_node.field_of_view,
        aspect=camera_node.aspect,
    )


def describe_camera_animations(camera_set, camera_index=0, logger=StubLogger()):
    """Decode CameraAnimation nodes from a CameraSet into IRCameraKeyframes.

    Walks the camera_set.animations array, decoding keyframes from:
    - The CameraAnimation's own AOBJ (FOV, roll, near, far, and optionally eye/target)
    - The eye_position_animation WObjectAnimation's AOBJ (eye XYZ)
    - The interest_animation WObjectAnimation's AOBJ (target XYZ)

    Args:
        camera_set: Parsed CameraSet node with .animations array.
        camera_index: Index for naming.
        logger: Logger instance.

    Returns:
        list[IRCameraKeyframes]
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
            _decode_aobj_tracks(aobj, _COBJ_TRACK_MAP, tracks, logger)

        # Decode eye WObjectAnimation's AOBJ
        eye_wobj_anim = getattr(cam_anim, 'eye_position_animation', None)
        if eye_wobj_anim:
            eye_aobj = getattr(eye_wobj_anim, 'animation', None)
            if eye_aobj:
                # Use eye AOBJ's end_frame if the main AOBJ was missing
                if end_frame == 0.0:
                    end_frame = getattr(eye_aobj, 'end_frame', 0.0) or 0.0
                _decode_aobj_tracks(eye_aobj, _WOBJ_EYE_MAP, tracks, logger)

        # Decode interest/target WObjectAnimation's AOBJ
        interest_wobj_anim = getattr(cam_anim, 'interest_animation', None)
        if interest_wobj_anim:
            interest_aobj = getattr(interest_wobj_anim, 'animation', None)
            if interest_aobj:
                if end_frame == 0.0:
                    end_frame = getattr(interest_aobj, 'end_frame', 0.0) or 0.0
                _decode_aobj_tracks(interest_aobj, _WOBJ_TARGET_MAP, tracks, logger)

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


def _decode_aobj_tracks(aobj, track_map, tracks, logger):
    """Walk an AOBJ's Frame chain and decode each track into the tracks dict.

    Args:
        aobj: Animation node with .frame linked list.
        track_map: dict mapping fobj.type → IRCameraKeyframes field name.
        tracks: output dict to populate (field_name → list[IRKeyframe]).
        logger: Logger instance.
    """
    fobj = getattr(aobj, 'frame', None)
    while fobj:
        fobj_type = getattr(fobj, 'type', None)
        field_name = track_map.get(fobj_type)
        if field_name is not None:
            keyframes = decode_fobjdesc(fobj, bias=0, scale=1.0)
            if keyframes:
                tracks[field_name] = keyframes
                logger.debug("    Decoded camera track type %s → %s: %d keyframes",
                             fobj_type, field_name, len(keyframes))
        fobj = getattr(fobj, 'next', None)
