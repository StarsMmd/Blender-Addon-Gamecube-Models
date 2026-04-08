"""Compose IRCamera into a CameraSet node tree.

Builds a Camera node with WObject position/interest and wraps it in a CameraSet.
Also encodes camera animations (IRCameraKeyframes) into CameraAnimation nodes.
"""
try:
    from .....shared.Nodes.Classes.Camera.Camera import Camera
    from .....shared.Nodes.Classes.Camera.CameraSet import CameraSet
    from .....shared.Nodes.Classes.Camera.CameraAnimation import CameraAnimation
    from .....shared.Nodes.Classes.Rendering.WObject import WObject
    from .....shared.Nodes.Classes.Rendering.WObjectAnimation import WObjectAnimation
    from .....shared.Nodes.Classes.Animation.Animation import Animation
    from .....shared.Nodes.Classes.Animation.Frame import Frame
    from .....shared.Constants.hsd import (
        COBJ_PROJECTION_PERSPECTIVE, COBJ_PROJECTION_ORTHO,
        HSD_A_C_EYEX, HSD_A_C_EYEY, HSD_A_C_EYEZ,
        HSD_A_C_ATX, HSD_A_C_ATY, HSD_A_C_ATZ,
        HSD_A_C_ROLL, HSD_A_C_FOVY, HSD_A_C_NEAR, HSD_A_C_FAR,
        HSD_A_W_TRAX, HSD_A_W_TRAY, HSD_A_W_TRAZ,
        AOBJ_ANIM_LOOP,
    )
    from .....shared.IR.enums import CameraProjection
    from .....shared.helpers.logger import StubLogger
    from .....shared.helpers.scale import METERS_TO_GC
except (ImportError, SystemError):
    from shared.Nodes.Classes.Camera.Camera import Camera
    from shared.Nodes.Classes.Camera.CameraSet import CameraSet
    from shared.Nodes.Classes.Camera.CameraAnimation import CameraAnimation
    from shared.Nodes.Classes.Rendering.WObject import WObject
    from shared.Nodes.Classes.Rendering.WObjectAnimation import WObjectAnimation
    from shared.Nodes.Classes.Animation.Animation import Animation
    from shared.Nodes.Classes.Animation.Frame import Frame
    from shared.Constants.hsd import (
        COBJ_PROJECTION_PERSPECTIVE, COBJ_PROJECTION_ORTHO,
        HSD_A_C_EYEX, HSD_A_C_EYEY, HSD_A_C_EYEZ,
        HSD_A_C_ATX, HSD_A_C_ATY, HSD_A_C_ATZ,
        HSD_A_C_ROLL, HSD_A_C_FOVY, HSD_A_C_NEAR, HSD_A_C_FAR,
        HSD_A_W_TRAX, HSD_A_W_TRAY, HSD_A_W_TRAZ,
        AOBJ_ANIM_LOOP,
    )
    from shared.IR.enums import CameraProjection
    from shared.helpers.logger import StubLogger
    from shared.helpers.scale import METERS_TO_GC

# Reuse the keyframe encoding logic from bone animations
from .animations import _encode_channel


_PROJECTION_TO_FLAG = {
    CameraProjection.PERSPECTIVE: COBJ_PROJECTION_PERSPECTIVE,
    CameraProjection.ORTHO: COBJ_PROJECTION_ORTHO,
}


def compose_camera(ir_camera, logger=StubLogger()):
    """Convert an IRCamera into a CameraSet node.

    Args:
        ir_camera: IRCamera from the IR.
        logger: Logger instance.

    Returns:
        CameraSet node, or None if ir_camera is None.
    """
    if ir_camera is None:
        return None

    camera = Camera(address=None, blender_obj=None)
    camera.name = None
    camera.flags = 0
    camera.perspective_flags = _PROJECTION_TO_FLAG.get(
        ir_camera.projection, COBJ_PROJECTION_PERSPECTIVE)
    camera.viewport = [0, 640, 0, 480]
    camera.scissor = [0, 640, 0, 480]
    camera.position = _make_wobject(ir_camera.position, scale=METERS_TO_GC)
    camera.interest = _make_wobject(ir_camera.target_position, scale=METERS_TO_GC)
    camera.roll = ir_camera.roll
    camera.up_vector = None
    camera.near = ir_camera.near * METERS_TO_GC
    camera.far = ir_camera.far * METERS_TO_GC
    camera.field_of_view = ir_camera.field_of_view
    camera.aspect = ir_camera.aspect

    camera_set = CameraSet(address=None, blender_obj=None)
    camera_set.camera = camera

    # Compose camera animations
    if ir_camera.animations:
        camera_set.animations = _compose_camera_animations(ir_camera.animations, logger)
    else:
        camera_set.animations = None

    logger.info("    Composed camera '%s'", ir_camera.name)
    return camera_set


def _compose_camera_animations(animations, logger):
    """Encode IRCameraKeyframes list into CameraAnimation nodes.

    Args:
        animations: list[IRCameraKeyframes] from the IR.
        logger: Logger instance.

    Returns:
        list[CameraAnimation] or None if empty.
    """
    results = []
    for anim in animations:
        cam_anim = _compose_single_camera_animation(anim, logger)
        if cam_anim:
            results.append(cam_anim)

    return results if results else None


def _compose_single_camera_animation(anim, logger):
    """Encode one IRCameraKeyframes into a CameraAnimation node.

    The CObj AOBJ carries FOV, roll, near, far tracks.
    Eye position tracks go into eye_position_animation (WObjectAnimation).
    Target position tracks go into interest_animation (WObjectAnimation).

    Args:
        anim: IRCameraKeyframes from the IR.
        logger: Logger instance.

    Returns:
        CameraAnimation node.
    """
    cam_anim = CameraAnimation(address=None, blender_obj=None)

    # Scale position/distance keyframes from meters back to GC units
    def _scale_kfs(kfs):
        if not kfs:
            return kfs
        from shared.IR.animation import IRKeyframe
        return [IRKeyframe(
            frame=kf.frame, value=kf.value * METERS_TO_GC,
            interpolation=kf.interpolation,
            handle_left=(kf.handle_left[0], kf.handle_left[1] * METERS_TO_GC) if kf.handle_left else None,
            handle_right=(kf.handle_right[0], kf.handle_right[1] * METERS_TO_GC) if kf.handle_right else None,
            slope_in=kf.slope_in * METERS_TO_GC if kf.slope_in is not None else None,
            slope_out=kf.slope_out * METERS_TO_GC if kf.slope_out is not None else None,
        ) for kf in kfs]

    # Build CObj AOBJ for FOV/roll/near/far
    cobj_channels = [
        (anim.fov, HSD_A_C_FOVY),
        (anim.roll, HSD_A_C_ROLL),
        (_scale_kfs(anim.near), HSD_A_C_NEAR),
        (_scale_kfs(anim.far), HSD_A_C_FAR),
    ]

    cobj_frames = _build_frame_chain(cobj_channels)
    if cobj_frames:
        aobj = Animation(address=None, blender_obj=None)
        aobj.flags = AOBJ_ANIM_LOOP if anim.loop else 0
        aobj.end_frame = float(anim.end_frame)
        aobj.frame = cobj_frames
        aobj.joint = None
        cam_anim.animation = aobj
    else:
        cam_anim.animation = None

    # Build eye position WObjectAnimation (scaled to GC)
    eye_channels = [
        (_scale_kfs(anim.eye_x), HSD_A_W_TRAX),
        (_scale_kfs(anim.eye_y), HSD_A_W_TRAY),
        (_scale_kfs(anim.eye_z), HSD_A_W_TRAZ),
    ]
    cam_anim.eye_position_animation = _build_wobject_animation(
        eye_channels, anim.end_frame, anim.loop)

    # Build target/interest WObjectAnimation (scaled to GC)
    target_channels = [
        (_scale_kfs(anim.target_x), HSD_A_W_TRAX),
        (_scale_kfs(anim.target_y), HSD_A_W_TRAY),
        (_scale_kfs(anim.target_z), HSD_A_W_TRAZ),
    ]
    cam_anim.interest_animation = _build_wobject_animation(
        target_channels, anim.end_frame, anim.loop)

    logger.debug("    Composed camera animation '%s'", anim.name)
    return cam_anim


def _build_wobject_animation(channels, end_frame, loop):
    """Build a WObjectAnimation node from position channels.

    Args:
        channels: list of (keyframes, channel_type) tuples.
        end_frame: Animation end frame.
        loop: Whether the animation loops.

    Returns:
        WObjectAnimation node, or None if no channels have data.
    """
    frames = _build_frame_chain(channels)
    if not frames:
        return None

    aobj = Animation(address=None, blender_obj=None)
    aobj.flags = AOBJ_ANIM_LOOP if loop else 0
    aobj.end_frame = float(end_frame)
    aobj.frame = frames
    aobj.joint = None

    wobj_anim = WObjectAnimation(address=None, blender_obj=None)
    wobj_anim.animation = aobj
    wobj_anim.render_animation = None
    return wobj_anim


def _build_frame_chain(channels):
    """Build a linked list of Frame nodes from channel data.

    Args:
        channels: list of (keyframes, channel_type) tuples.

    Returns:
        First Frame node in the chain, or None if no data.
    """
    frames = []
    for keyframes, channel_type in channels:
        if not keyframes:
            continue
        frame = _encode_channel(keyframes, channel_type)
        if frame is not None:
            frames.append(frame)

    # Link frames into list
    for i in range(len(frames) - 1):
        frames[i].next = frames[i + 1]

    return frames[0] if frames else None


def _make_wobject(position, scale=1.0):
    """Create a WObject with a position vec3, optionally scaled."""
    wobj = WObject(address=None, blender_obj=None)
    wobj.name = None
    wobj.position = [p * scale for p in position] if position else [0.0, 0.0, 0.0]
    wobj.render = None
    return wobj
