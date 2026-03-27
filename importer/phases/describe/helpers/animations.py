"""Describe animation data from AnimationJoint trees.

Walks AnimationJoint tree parallel to Joint tree, decoding HSD
keyframes into generic IRBoneAnimationSet / IRBoneTrack / IRKeyframe.
"""
try:
    from .....shared.Constants.hsd import *
    from .....shared.helpers.logger import StubLogger
    from .....shared.helpers.math_shim import Matrix, Vector, compile_srt_matrix, matrix_to_list
    from .....shared.IR.animation import IRBoneAnimationSet, IRBoneTrack, IRKeyframe
    from .....shared.IR.enums import Interpolation
    from .keyframe_decoder import decode_fobjdesc
except (ImportError, SystemError):
    from shared.Constants.hsd import *
    from shared.helpers.logger import StubLogger
    from shared.helpers.math_shim import Matrix, Vector, compile_srt_matrix, matrix_to_list
    from shared.IR.animation import IRBoneAnimationSet, IRBoneTrack, IRKeyframe
    from shared.IR.enums import Interpolation
    from importer.phases.describe.helpers.keyframe_decoder import decode_fobjdesc


def _find_spline(joint, logger=None):
    """Find a Spline node on this joint or its JOBJ_SPLINE child."""
    # Check the joint itself first
    if joint.property and hasattr(joint.property, 's1'):
        if logger:
            logger.debug("    _find_spline: found on joint 0x%X itself", joint.address)
        return joint.property
    # Check child joints for JOBJ_SPLINE flag
    child = getattr(joint, 'child', None)
    if logger:
        logger.debug("    _find_spline: joint 0x%X property=%s flags=0x%X child=%s",
                     joint.address,
                     type(joint.property).__name__ if joint.property else 'None',
                     getattr(joint, 'flags', 0),
                     ('0x%X' % child.address) if child else 'None')
    while child:
        child_flags = getattr(child, 'flags', 0)
        child_prop = getattr(child, 'property', None)
        if logger:
            logger.debug("    _find_spline: checking child 0x%X flags=0x%X property=%s has_s1=%s",
                         child.address, child_flags,
                         type(child_prop).__name__ if child_prop else 'None',
                         hasattr(child_prop, 's1') if child_prop else False)
        if child_flags & JOBJ_SPLINE:
            if child_prop and hasattr(child_prop, 's1'):
                return child_prop
        child = getattr(child, 'next', None)
    return None


def _bake_path_to_location(path_keyframes, spline_points, end_frame,
                           parent_world_matrix, logger=None, bone_name=''):
    """Bake path parameter keyframes + spline control points into XYZ location keyframes.

    Spline positions are in HSD world space. These are converted to bone-local
    SRT translation values (the same space as joint.position) by multiplying
    by the inverse of the parent's world matrix.

    Returns [X_keyframes, Y_keyframes, Z_keyframes] in bone-local space,
    ready to be processed by the normal SRT baking pipeline in the build phase.
    """
    num_points = len(spline_points)
    num_segments = num_points - 1
    if num_segments <= 0:
        return [[], [], []]

    # Inverse parent world matrix to convert world → bone-local translation
    if parent_world_matrix:
        inv_parent = parent_world_matrix.inverted()
    else:
        inv_parent = None

    # Build a simple piecewise-linear sampler for the path parameter.
    sorted_kf = sorted(path_keyframes, key=lambda kf: kf.frame)

    def _eval_param(frame):
        """Evaluate path parameter at a given frame via linear interpolation."""
        if not sorted_kf:
            return 0.0
        if frame <= sorted_kf[0].frame:
            return sorted_kf[0].value
        if frame >= sorted_kf[-1].frame:
            return sorted_kf[-1].value
        for i in range(len(sorted_kf) - 1):
            kf0 = sorted_kf[i]
            kf1 = sorted_kf[i + 1]
            if kf0.frame <= frame <= kf1.frame:
                if kf1.frame == kf0.frame:
                    return kf0.value
                t = (frame - kf0.frame) / (kf1.frame - kf0.frame)
                return kf0.value + t * (kf1.value - kf0.value)
        return sorted_kf[-1].value

    loc_x, loc_y, loc_z = [], [], []

    for frame in range(end_frame):
        param = _eval_param(float(frame))
        # Scale normalized parameter (0-1) to spline index range
        t = param * num_segments
        t = max(0.0, min(t, float(num_segments)))
        idx = int(t)
        frac = t - idx
        if idx >= num_segments:
            idx = num_segments - 1
            frac = 1.0

        p0 = spline_points[idx]
        p1 = spline_points[idx + 1]
        world_pos = Vector((
            p0[0] + frac * (p1[0] - p0[0]),
            p0[1] + frac * (p1[1] - p0[1]),
            p0[2] + frac * (p1[2] - p0[2]),
        ))

        # Convert world position to bone-local translation
        if inv_parent:
            local_pos = inv_parent @ world_pos
        else:
            local_pos = world_pos

        loc_x.append(IRKeyframe(frame=float(frame), value=local_pos[0], interpolation=Interpolation.LINEAR))
        loc_y.append(IRKeyframe(frame=float(frame), value=local_pos[1], interpolation=Interpolation.LINEAR))
        loc_z.append(IRKeyframe(frame=float(frame), value=local_pos[2], interpolation=Interpolation.LINEAR))

    if logger and loc_x:
        mid = len(loc_x) // 2
        logger.info("    path bake: frame 0 local=(%.4f, %.4f, %.4f)",
                    loc_x[0].value, loc_y[0].value, loc_z[0].value)
        logger.info("    path bake: frame %d local=(%.4f, %.4f, %.4f)",
                    mid, loc_x[mid].value, loc_y[mid].value, loc_z[mid].value)
        logger.info("    path bake: frame %d local=(%.4f, %.4f, %.4f)",
                    len(loc_x) - 1, loc_x[-1].value, loc_y[-1].value, loc_z[-1].value)

    return [loc_x, loc_y, loc_z]


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
    animated_joints = getattr(model_set, 'animated_joints', None) or []
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
    path_keyframes = None
    spline_points = None
    spline_type = 0
    spline_tension = 0.0
    spline_num_cvs = 0
    spline_world_matrix = None

    fobj = aobj.frame
    while fobj:
        if fobj.type == HSD_A_J_PATH:
            path_keyframes = decode_fobjdesc(fobj)
            # The Animation object's 'joint' field points to the spline joint
            spline_joint = getattr(aobj, 'joint', None)
            spline_node = None
            if spline_joint and hasattr(spline_joint, 'property') and spline_joint.property:
                prop = spline_joint.property
                if hasattr(prop, 's1') and not isinstance(prop, int):
                    spline_node = prop
            # Fallback: check the current joint or its JOBJ_SPLINE children
            if spline_node is None:
                spline_node = _find_spline(joint, logger)
            if spline_node and hasattr(spline_node, 's1') and isinstance(spline_node.s1, list) and spline_node.s1:
                spline_points = [list(p) for p in spline_node.s1]
                spline_type = getattr(spline_node, 'flags', 0) >> 8
                spline_tension = getattr(spline_node, 'f0', 0.0) or 0.0
                spline_num_cvs = getattr(spline_node, 'n', 0)
                # Store spline joint's local SRT for curve positioning
                if spline_joint:
                    spline_joint_srt = (
                        tuple(spline_joint.scale),
                        tuple(spline_joint.rotation),
                        tuple(spline_joint.position),
                    )
                    # Compute world matrix for the spline joint
                    spline_local = compile_srt_matrix(
                        spline_joint.scale, spline_joint.rotation, spline_joint.position
                    )
                    # The spline joint's parent is the path bone's parent
                    if bone.parent_index is not None:
                        parent_world = Matrix(bones[bone.parent_index].world_matrix)
                        spline_world = parent_world @ spline_local
                    else:
                        spline_world = spline_local
                    spline_world_matrix = matrix_to_list(spline_world)

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

    if path_keyframes and spline_points and logger:
        logger.info("  PATH bone '%s' (idx=%d): %d path kf, %d spline pts (type=%d)",
                    bone.name, bone_index, len(path_keyframes), len(spline_points), spline_type)

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
        path_keyframes=path_keyframes if path_keyframes else None,
        spline_points=spline_points if spline_points else None,
        spline_type=spline_type,
        spline_tension=spline_tension,
        spline_num_cvs=spline_num_cvs,
        spline_world_matrix=spline_world_matrix if spline_points else None,
    )
