"""Compose IRMaterialTrack into MaterialAnimationJoint node trees.

Builds MaterialAnimationJoint trees (parallel to Joint tree) from
IRMaterialTrack data in each IRBoneAnimationSet. Each track maps to
a MaterialAnimation node attached to the bone that owns the mesh.
"""
import re
from collections import defaultdict

try:
    from .....shared.Nodes.Classes.Material.MaterialAnimationJoint import MaterialAnimationJoint
    from .....shared.Nodes.Classes.Material.MaterialAnimation import MaterialAnimation
    from .....shared.Nodes.Classes.Texture.TextureAnimation import TextureAnimation
    from .....shared.Nodes.Classes.Animation.Animation import Animation
    from .....shared.Nodes.Classes.Animation.Frame import Frame
    from .....shared.Constants.hsd import (
        HSD_A_M_DIFFUSE_R, HSD_A_M_DIFFUSE_G, HSD_A_M_DIFFUSE_B, HSD_A_M_ALPHA,
        HSD_A_T_TRAU, HSD_A_T_TRAV, HSD_A_T_SCAU, HSD_A_T_SCAV,
        HSD_A_T_ROTX, HSD_A_T_ROTY, HSD_A_T_ROTZ,
        AOBJ_ANIM_LOOP,
    )
    from .....shared.helpers.logger import StubLogger
    from .animations import _encode_channel
except (ImportError, SystemError):
    from shared.Nodes.Classes.Material.MaterialAnimationJoint import MaterialAnimationJoint
    from shared.Nodes.Classes.Material.MaterialAnimation import MaterialAnimation
    from shared.Nodes.Classes.Texture.TextureAnimation import TextureAnimation
    from shared.Nodes.Classes.Animation.Animation import Animation
    from shared.Nodes.Classes.Animation.Frame import Frame
    from shared.Constants.hsd import (
        HSD_A_M_DIFFUSE_R, HSD_A_M_DIFFUSE_G, HSD_A_M_DIFFUSE_B, HSD_A_M_ALPHA,
        HSD_A_T_TRAU, HSD_A_T_TRAV, HSD_A_T_SCAU, HSD_A_T_SCAV,
        HSD_A_T_ROTX, HSD_A_T_ROTY, HSD_A_T_ROTZ,
        AOBJ_ANIM_LOOP,
    )
    from shared.helpers.logger import StubLogger
    from exporter.phases.compose.helpers.animations import _encode_channel

# IR field → HSD channel type for material color/alpha
_COLOR_CHANNELS = [
    ('diffuse_r', HSD_A_M_DIFFUSE_R),
    ('diffuse_g', HSD_A_M_DIFFUSE_G),
    ('diffuse_b', HSD_A_M_DIFFUSE_B),
    ('alpha',     HSD_A_M_ALPHA),
]

# IR field → HSD channel type for texture UV
_UV_CHANNELS = [
    ('translation_u', HSD_A_T_TRAU),
    ('translation_v', HSD_A_T_TRAV),
    ('scale_u',       HSD_A_T_SCAU),
    ('scale_v',       HSD_A_T_SCAV),
    ('rotation_x',    HSD_A_T_ROTX),
    ('rotation_y',    HSD_A_T_ROTY),
    ('rotation_z',    HSD_A_T_ROTZ),
]


def compose_material_animations(anim_set, bones, logger=StubLogger()):
    """Build a MaterialAnimationJoint tree from one IRBoneAnimationSet.

    Args:
        anim_set: IRBoneAnimationSet with material_tracks populated.
        bones: list[IRBone] from the IR.
        logger: Logger instance.

    Returns:
        MaterialAnimationJoint root, or None if no material tracks.
    """
    if not anim_set.material_tracks:
        return None

    # Map mesh_index → bone_index from the IRBone mesh_indices lists
    mesh_to_bone = {}
    for bone_idx, bone in enumerate(bones):
        for mesh_idx in bone.mesh_indices:
            mesh_to_bone[mesh_idx] = bone_idx

    # Group material tracks by bone index
    tracks_by_bone = defaultdict(list)
    for track in anim_set.material_tracks:
        mesh_idx = _parse_mesh_index(track.material_mesh_name)
        bone_idx = mesh_to_bone.get(mesh_idx)
        if bone_idx is not None:
            tracks_by_bone[bone_idx].append(track)

    # Create MaterialAnimationJoint for every bone
    mat_joints = []
    for i, bone in enumerate(bones):
        maj = MaterialAnimationJoint(address=None, blender_obj=None)
        maj.child = None
        maj.next = None

        tracks = tracks_by_bone.get(i, [])
        if tracks:
            maj.animation = _build_material_animation_chain(tracks, anim_set.loop)
        else:
            maj.animation = None

        mat_joints.append(maj)

    # Reconstruct child/next tree from parent_index
    children_of = defaultdict(list)
    roots = []
    for i, bone in enumerate(bones):
        if bone.parent_index is None:
            roots.append(i)
        else:
            children_of[bone.parent_index].append(i)

    for parent_idx, child_indices in children_of.items():
        mat_joints[parent_idx].child = mat_joints[child_indices[0]]
        for j in range(1, len(child_indices)):
            mat_joints[child_indices[j - 1]].next = mat_joints[child_indices[j]]

    for j in range(1, len(roots)):
        mat_joints[roots[j - 1]].next = mat_joints[roots[j]]

    track_count = sum(len(t) for t in tracks_by_bone.values())
    logger.info("    Composed material animation: %d track(s) across %d bone(s)",
                track_count, len(tracks_by_bone))

    return mat_joints[roots[0]] if roots else None


def _parse_mesh_index(material_mesh_name):
    """Extract mesh index from material_mesh_name like 'mesh_15_Bone_103'."""
    match = re.match(r'mesh_(\d+)_', material_mesh_name)
    if match:
        return int(match.group(1))
    return 0


def _build_material_animation_chain(tracks, loop):
    """Build a linked list of MaterialAnimation nodes from tracks for one bone.

    Each track becomes one MaterialAnimation in the chain (one per DObj/mesh).
    """
    mat_anims = []
    for track in tracks:
        ma = _build_material_animation(track, loop)
        if ma is not None:
            mat_anims.append(ma)

    if not mat_anims:
        return None

    for i in range(len(mat_anims) - 1):
        mat_anims[i].next = mat_anims[i + 1]

    return mat_anims[0]


def _build_material_animation(track, loop):
    """Build a MaterialAnimation node from one IRMaterialTrack."""
    ma = MaterialAnimation(address=None, blender_obj=None)
    ma.next = None
    ma.render_animation = None

    # Color/alpha animation
    color_frames = []
    for field_name, channel_type in _COLOR_CHANNELS:
        keyframes = getattr(track, field_name, None)
        if keyframes:
            # Scale values back to [0-255] range for HSD encoding
            scaled = []
            for kf in keyframes:
                from copy import copy
                skf = copy(kf)
                skf.value = kf.value * 255.0
                if kf.slope_in is not None:
                    skf.slope_in = kf.slope_in * 255.0
                if kf.slope_out is not None:
                    skf.slope_out = kf.slope_out * 255.0
                scaled.append(skf)
            frame = _encode_channel(scaled, channel_type)
            if frame is not None:
                color_frames.append(frame)

    if color_frames:
        for i in range(len(color_frames) - 1):
            color_frames[i].next = color_frames[i + 1]
        anim = Animation(address=None, blender_obj=None)
        anim.flags = AOBJ_ANIM_LOOP if loop else 0
        anim.end_frame = _end_frame_from_keyframes(
            track.diffuse_r, track.diffuse_g, track.diffuse_b, track.alpha)
        anim.joint = None
        anim.frame = color_frames[0]
        ma.animation = anim
    else:
        ma.animation = None

    # Texture UV animations
    tex_anims = []
    for uv_track in track.texture_uv_tracks:
        ta = _build_texture_animation(uv_track, loop)
        if ta is not None:
            tex_anims.append(ta)

    if tex_anims:
        for i in range(len(tex_anims) - 1):
            tex_anims[i].next = tex_anims[i + 1]
        ma.texture_animation = tex_anims[0]
    else:
        ma.texture_animation = None

    # Only return if there's actual animation data
    if ma.animation is None and ma.texture_animation is None:
        return None

    return ma


def _build_texture_animation(uv_track, loop):
    """Build a TextureAnimation node from one IRTextureUVTrack."""
    uv_frames = []
    for field_name, channel_type in _UV_CHANNELS:
        keyframes = getattr(uv_track, field_name, None)
        if keyframes:
            # Reverse V-flip for translation_v: GX uses top-left origin
            if field_name == 'translation_v':
                keyframes = _unflip_translation_v(
                    keyframes, uv_track.scale_v)

            frame = _encode_channel(keyframes, channel_type)
            if frame is not None:
                uv_frames.append(frame)

    if not uv_frames:
        return None

    for i in range(len(uv_frames) - 1):
        uv_frames[i].next = uv_frames[i + 1]

    all_kf_lists = []
    for field_name, _ in _UV_CHANNELS:
        kfs = getattr(uv_track, field_name, None)
        if kfs:
            all_kf_lists.append(kfs)

    anim = Animation(address=None, blender_obj=None)
    anim.flags = AOBJ_ANIM_LOOP if loop else 0
    anim.end_frame = _end_frame_from_keyframes(*all_kf_lists)
    anim.joint = None
    anim.frame = uv_frames[0]

    ta = TextureAnimation(address=None, blender_obj=None)
    ta.next = None
    ta.id = uv_track.texture_index
    ta.animation = anim
    ta.image_table_count = 0
    ta.palette_table_count = 0

    return ta


def _unflip_translation_v(translation_kfs, scale_kfs):
    """Reverse the V-flip applied during import.

    Import applied: v_ir = 1 - scale_v - v_gx
    Reverse:        v_gx = 1 - scale_v - v_ir

    The formula is self-inverse, so the same operation reverses it.
    """
    from copy import copy

    if not scale_kfs:
        # Static scale — use 1.0 as default (matching import's static_scale_v)
        result = []
        for kf in translation_kfs:
            skf = copy(kf)
            skf.value = 1.0 - 1.0 - kf.value  # scale_v=1.0 default
            # Slopes negate (derivative of -v is -slope)
            if kf.slope_in is not None:
                skf.slope_in = -kf.slope_in
            if kf.slope_out is not None:
                skf.slope_out = -kf.slope_out
            result.append(skf)
        return result

    # Animated scale — evaluate scale at each keyframe's frame
    try:
        from .....importer.phases.describe.helpers.material_animations import _evaluate_track
    except (ImportError, SystemError):
        from importer.phases.describe.helpers.material_animations import _evaluate_track

    result = []
    for kf in translation_kfs:
        skf = copy(kf)
        scale_at_frame = _evaluate_track(scale_kfs, kf.frame)
        skf.value = 1.0 - scale_at_frame - kf.value
        if kf.slope_in is not None:
            skf.slope_in = -kf.slope_in
        if kf.slope_out is not None:
            skf.slope_out = -kf.slope_out
        result.append(skf)
    return result


def _end_frame_from_keyframes(*channel_lists):
    """Get the maximum frame value across multiple keyframe channel lists."""
    max_frame = 0.0
    for channel in channel_lists:
        if channel:
            for kf in channel:
                max_frame = max(max_frame, kf.frame)
    return max_frame
