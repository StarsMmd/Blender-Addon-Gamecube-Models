"""Describe animation data from AnimationJoint trees.

Walks AnimationJoint tree parallel to Joint tree, decoding HSD
keyframes into generic IRBoneAnimationSet / IRBoneTrack / IRKeyframe.
"""
try:
    from .....shared.Constants.hsd import *
    from .....shared.helpers.logger import StubLogger
    from .....shared.helpers.math_shim import Matrix, compile_srt_matrix, matrix_to_list
    from .....shared.IR.animation import IRBoneAnimationSet, IRBoneTrack, IRSplinePath, IRKeyframe
    from .....shared.IR.enums import Interpolation
    from .keyframe_decoder import decode_fobjdesc
except (ImportError, SystemError):
    from shared.Constants.hsd import *
    from shared.helpers.logger import StubLogger
    from shared.helpers.math_shim import Matrix, compile_srt_matrix, matrix_to_list
    from shared.IR.animation import IRBoneAnimationSet, IRBoneTrack, IRSplinePath, IRKeyframe
    from shared.IR.enums import Interpolation
    from importer.phases.describe.helpers.keyframe_decoder import decode_fobjdesc


# HSD channel type → (category, component_index)
# category: 'r'=rotation, 'l'=location, 's'=scale
_CHANNEL_MAP = {
    HSD_A_J_ROTX: ('r', 0), HSD_A_J_ROTY: ('r', 1), HSD_A_J_ROTZ: ('r', 2),
    HSD_A_J_TRAX: ('l', 0), HSD_A_J_TRAY: ('l', 1), HSD_A_J_TRAZ: ('l', 2),
    HSD_A_J_SCAX: ('s', 0), HSD_A_J_SCAY: ('s', 1), HSD_A_J_SCAZ: ('s', 2),
}


def describe_bone_animations(model_set, joint_to_bone_index, bones, options, logger=StubLogger(), model_name=None):
    """Walk AnimationJoint trees and produce IRBoneAnimationSet list.

    Args:
        model_set: Parsed model set with animated_joints list.
        joint_to_bone_index: dict mapping Joint.address → bone index.
        bones: list[IRBone] from describe_bones().
        options: importer options dict.
        logger: Logger instance.
        model_name: Name to use for animation naming (defaults to root joint name).

    Returns:
        list[IRBoneAnimationSet] with decoded keyframes per bone per channel.
    """
    animated_joints = getattr(model_set, 'animated_joints', None) or []
    root_joint = model_set.root_joint
    name_prefix = model_name or root_joint.name or "Model"
    anim_sets = []

    for i, anim_joint_root in enumerate(animated_joints):
        name = "%s_Anim_%02d" % (name_prefix, i)
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
            track = _describe_bone_track(aobj, joint, bone, bone_index, bones, logger)
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


def _describe_bone_track(aobj, joint, bone, bone_index, bones, logger=None):
    """Decode all channels for one bone into an IRBoneTrack."""
    rotation = [[], [], []]  # [X, Y, Z]
    location = [[], [], []]
    scale = [[], [], []]
    spline_path = None

    fobj = aobj.frame
    while fobj:
        if fobj.type == HSD_A_J_PATH:
            spline_path = _extract_spline_path(aobj, joint, bone, bones, fobj, logger)

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

    if spline_path and logger:
        logger.info("  PATH bone '%s' (idx=%d): %d param kf, %d control pts (type=%d)",
                    bone.name, bone_index, len(spline_path.parameter_keyframes),
                    len(spline_path.control_points), spline_path.curve_type)

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
        end_frame=aobj.end_frame,
        spline_path=spline_path,
    )


def _extract_spline_path(aobj, joint, bone, bones, fobj, logger):
    """Extract spline path data from a PATH animation channel into IRSplinePath."""
    path_keyframes = decode_fobjdesc(fobj)
    if not path_keyframes:
        return None

    # The Animation object's 'joint' field points to the spline joint
    spline_joint = getattr(aobj, 'joint', None)
    spline_node = None
    if spline_joint and hasattr(spline_joint, 'property') and spline_joint.property:
        prop = spline_joint.property
        if hasattr(prop, 's1') and not isinstance(prop, int):
            spline_node = prop

    if spline_node is None or not isinstance(getattr(spline_node, 's1', None), list):
        return None

    control_points = [list(p) for p in spline_node.s1]
    curve_type = getattr(spline_node, 'flags', 0) >> 8
    tension = getattr(spline_node, 'f0', 0.0) or 0.0
    num_cvs = getattr(spline_node, 'n', 0)

    # Compute world matrix for the spline joint (for curve positioning)
    world_matrix = None
    if spline_joint:
        spline_local = compile_srt_matrix(
            spline_joint.scale, spline_joint.rotation, spline_joint.position
        )
        if bone.parent_index is not None:
            parent_world = Matrix(bones[bone.parent_index].world_matrix)
            spline_world = parent_world @ spline_local
        else:
            spline_world = spline_local
        world_matrix = matrix_to_list(spline_world)

    return IRSplinePath(
        control_points=control_points,
        parameter_keyframes=path_keyframes,
        curve_type=curve_type,
        tension=tension,
        num_control_points=num_cvs,
        world_matrix=world_matrix,
    )
