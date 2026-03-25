"""Describe animation data from AnimationJoint trees.

Walks AnimationJoint tree parallel to Joint tree, decoding HSD
keyframes into generic IRBoneAnimationSet / IRBoneTrack / IRKeyframe.
"""
try:
    from .....shared.Constants.hsd import *
    from .....shared.helpers.logger import StubLogger
    from .....shared.IR.animation import IRBoneAnimationSet, IRBoneTrack, IRKeyframe
    from .....shared.IR.enums import Interpolation
    from .keyframe_decoder import decode_fobjdesc
except (ImportError, SystemError):
    from shared.Constants.hsd import *
    from shared.helpers.logger import StubLogger
    from shared.IR.animation import IRBoneAnimationSet, IRBoneTrack, IRKeyframe
    from shared.IR.enums import Interpolation
    from importer.phases.describe.helpers.keyframe_decoder import decode_fobjdesc


# HSD channel type → (category, component_index)
# category: 'r'=rotation, 'l'=location, 's'=scale
_CHANNEL_MAP = {
    HSD_A_J_ROTX: ('r', 0), HSD_A_J_ROTY: ('r', 1), HSD_A_J_ROTZ: ('r', 2),
    HSD_A_J_TRAX: ('l', 0), HSD_A_J_TRAY: ('l', 1), HSD_A_J_TRAZ: ('l', 2),
    HSD_A_J_SCAX: ('s', 0), HSD_A_J_SCAY: ('s', 1), HSD_A_J_SCAZ: ('s', 2),
}


def describe_bone_animations(model_set, joint_to_bone_index, bones, options, logger=StubLogger()):
    """Walk AnimationJoint trees and produce IRBoneAnimationSet list.

    Args:
        model_set: Parsed model set with animated_joints list.
        joint_to_bone_index: dict mapping Joint.address → bone index.
        bones: list[IRBone] from describe_bones().
        options: importer options dict.
        logger: Logger instance.

    Returns:
        list[IRBoneAnimationSet] with decoded keyframes per bone per channel.
    """
    animated_joints = getattr(model_set, 'animated_joints', [])
    root_joint = model_set.root_joint
    anim_sets = []

    for i, anim_joint_root in enumerate(animated_joints):
        name = "%s_Anim_%02d" % (root_joint.name or "Model", i)
        tracks = []
        loop = [False]  # mutable for closure

        _walk_parallel(anim_joint_root, root_joint, tracks, loop,
                       joint_to_bone_index, bones, logger)

        anim_set = IRBoneAnimationSet(
            name=name,
            tracks=tracks,
            loop=loop[0],
        )
        anim_sets.append(anim_set)
        logger.debug("  Animation set '%s': %d bone tracks", name, len(tracks))

    return anim_sets


def _walk_parallel(anim_joint, joint, tracks, loop_flag,
                   joint_to_bone_index, bones, logger):
    """Walk AnimationJoint and Joint trees in parallel, decoding keyframes."""
    bone_index = joint_to_bone_index.get(joint.address, 0)
    bone = bones[bone_index]

    if anim_joint.animation:
        aobj = anim_joint.animation

        if not (aobj.flags & AOBJ_NO_ANIM):
            track = _describe_bone_track(aobj, joint, bone, bone_index, bones)
            if track is not None:
                tracks.append(track)
                is_loop = bool(aobj.flags & AOBJ_ANIM_LOOP)
                loop_flag[0] = loop_flag[0] or is_loop

    if anim_joint.child and joint.child:
        _walk_parallel(anim_joint.child, joint.child, tracks, loop_flag,
                       joint_to_bone_index, bones, logger)
    if anim_joint.next and joint.next:
        _walk_parallel(anim_joint.next, joint.next, tracks, loop_flag,
                       joint_to_bone_index, bones, logger)


def _describe_bone_track(aobj, joint, bone, bone_index, bones):
    """Decode all channels for one bone into an IRBoneTrack."""
    rotation = [[], [], []]  # [X, Y, Z]
    location = [[], [], []]
    scale = [[], [], []]
    has_path = False
    path_keyframes = None
    spline_points = None

    fobj = aobj.frame
    while fobj:
        if fobj.type == HSD_A_J_PATH:
            has_path = True
            path_keyframes = decode_fobjdesc(fobj)
            if joint.property and hasattr(joint.property, 's1') and joint.property.s1:
                spline_points = [list(p) for p in joint.property.s1]

        elif fobj.type in _CHANNEL_MAP:
            category, component = _CHANNEL_MAP[fobj.type]
            keyframes = decode_fobjdesc(fobj)

            if category == 'r':
                rotation[component] = keyframes
            elif category == 'l':
                location[component] = keyframes
            elif category == 's':
                scale[component] = keyframes

        fobj = fobj.next

    # Parent accumulated scale
    parent_scl = None
    if bone.parent_index is not None:
        parent_bone = bones[bone.parent_index]
        parent_scl = parent_bone.accumulated_scale

    return IRBoneTrack(
        bone_name=bone.name,
        bone_index=bone_index,
        rotation=rotation,
        location=location,
        scale=scale,
        rest_rotation=tuple(joint.rotation),
        rest_position=tuple(joint.position),
        rest_scale=tuple(joint.scale),
        parent_accumulated_scale=parent_scl,
        path_keyframes=path_keyframes if has_path else None,
        spline_points=spline_points if has_path else None,
    )
