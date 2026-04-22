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
    from .....shared.helpers.scale import GC_TO_METERS
except (ImportError, SystemError):
    from shared.Constants.hsd import *
    from shared.helpers.logger import StubLogger
    from shared.helpers.math_shim import Matrix, compile_srt_matrix, matrix_to_list
    from shared.IR.animation import IRBoneAnimationSet, IRBoneTrack, IRSplinePath, IRKeyframe
    from shared.IR.enums import Interpolation
    from shared.helpers.scale import GC_TO_METERS
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

    # Build semantic name map from PKX header if available
    anim_name_map = _build_anim_name_map(options.get("pkx_header"))

    anim_sets = []
    total_anims = len(animated_joints)
    anim_digits = len(str(max(total_anims - 1, 0))) if total_anims > 0 else 1
    name_counts = {}  # track how many times each semantic name has been used

    has_pkx = bool(anim_name_map)

    for i, anim_joint_root in enumerate(animated_joints):
        tracks = []
        loop = [False]  # mutable for closure

        _walk_parallel(anim_joint_root, root_joint, tracks, loop,
                       joint_to_bone_index, bones, logger, options)

        semantic = anim_name_map.get(i)
        if semantic:
            # Clean up: replace " + " with "+" first, then spaces with "_"
            clean = semantic.replace(' + ', '+').replace(' ', '_')
        elif has_pkx:
            clean = "Extra"
        else:
            clean = "Pose" if _is_static_pose(tracks) else "Anim"

        # Deduplicate: first occurrence is bare, subsequent get "_2", "_3", etc.
        if clean in name_counts:
            name_counts[clean] += 1
            clean = "%s_%d" % (clean, name_counts[clean])
        else:
            name_counts[clean] = 1

        # Infix padded index after model name to preserve import order alphabetically
        idx_str = str(i).zfill(anim_digits)
        name = "%s_%s_%s" % (name_prefix, idx_str, clean)

        anim_set = IRBoneAnimationSet(
            name=name,
            tracks=tracks,
            loop=loop[0],
        )
        anim_sets.append(anim_set)
        logger.debug("  Animation set '%s': %d bone tracks", name, len(tracks))

    return anim_sets


def _is_static_pose(tracks):
    """Return True if every keyframe channel in the tracks holds a constant value."""
    for track in tracks:
        for kf_list in (track.rotation, track.location, track.scale):
            if kf_list is None:
                continue
            for axis_kfs in kf_list:
                if axis_kfs and len(axis_kfs) > 1:
                    first = axis_kfs[0].value
                    for kf in axis_kfs[1:]:
                        if abs(kf.value - first) > 1e-6:
                            return False
    return True


def _build_anim_name_map(pkx_header):
    """Build a map of animation index → semantic name from PKX metadata.

    Uses the animation slot entries and sub-animation references to produce
    compact, human-readable names for each DAT animation index.

    Returns dict[int, str] or empty dict if no PKX header.
    """
    if pkx_header is None:
        return {}

    try:
        from .....shared.helpers.pkx_header import XD_POKEMON_ANIM_NAMES, XD_TRAINER_ANIM_NAMES
    except (ImportError, SystemError):
        from shared.helpers.pkx_header import XD_POKEMON_ANIM_NAMES, XD_TRAINER_ANIM_NAMES

    is_xd = pkx_header.is_xd
    is_trainer = is_xd and pkx_header.species_id == 0 and pkx_header.particle_orientation == 0
    slot_names = XD_TRAINER_ANIM_NAMES if is_trainer else XD_POKEMON_ANIM_NAMES

    # Collect active slot names per animation index.
    # XD uses motion_type > 0 to indicate active entries.
    # Colosseum uses motion_type=0 as the default active state, so we check
    # whether the entry's anim_type indicates a configured slot instead.
    _COLO_ACTIVE_TYPES = {2, 3, 5}  # loop, hit_reaction, compound
    index_to_slots = {}
    for slot_idx, entry in enumerate(pkx_header.anim_entries):
        slot_name = slot_names[slot_idx] if slot_idx < len(slot_names) else 'Slot %d' % slot_idx
        for sub in entry.sub_anims:
            if sub.anim_index >= 1000:
                continue
            if is_xd:
                active = sub.motion_type > 0
            else:
                # Colosseum: entry is active if anim_type is non-default or motion_type > 0
                active = entry.anim_type in _COLO_ACTIVE_TYPES or sub.motion_type > 0
            if active:
                idx = sub.anim_index
                if idx not in index_to_slots:
                    index_to_slots[idx] = []
                if slot_name not in index_to_slots[idx]:
                    index_to_slots[idx].append(slot_name)

    # Add sub-animation references
    sub_triggers = {0: 'Sub SleepOnPose', 1: 'Sub SleepOffPose', 2: 'Sub Extra'}
    for i in range(min(len(pkx_header.part_anim_data), 3)):
        pad = pkx_header.part_anim_data[i]
        if pad.has_data > 0 and pad.anim_index_ref > 0:
            idx = pad.anim_index_ref
            if idx not in index_to_slots:
                index_to_slots[idx] = []
            index_to_slots[idx].append(sub_triggers.get(i, 'Sub %d' % i))

    # Compact names
    result = {}
    for idx, names in index_to_slots.items():
        result[idx] = _compact_anim_name(names)

    return result


def _compact_anim_name(slot_names):
    """Generate a compact animation name from a list of slot names.

    Rules:
    - "Idle" (slot 0) takes absolute priority — always just "Idle"
    - Sub-animations keep their prefix: "Sub SleepOnPose"
    - Physical-only → "Physical", Special-only → "Special", mix → "Attack"
    - Non-attack slots appended after (except regularly defaulting ones like Take Flight)
    - Damage + Faint sharing → "Faint"
    - Deduplication happens upstream after all names are generated
    """
    if not slot_names:
        return 'Unknown'

    # Idle (slot 0) takes absolute priority — extras may share the idle
    # animation but get the 'Idle' label when they do.
    if 'Idle' in slot_names:
        return 'Idle'

    # Sub-animations take priority
    subs = [n for n in slot_names if n.startswith('Sub ')]
    if subs:
        return subs[0]

    if len(slot_names) == 1:
        return slot_names[0]

    # Categorize
    physical = sorted([n for n in slot_names if 'Physical' in n])
    special = sorted([n for n in slot_names if 'Special' in n])
    damage = sorted([n for n in slot_names if 'Damage' in n])
    faint = [n for n in slot_names if n == 'Faint']

    # Slots that regularly default to sharing an animation — don't mention
    _DEFAULT_SLOTS = {'Take Flight'}
    _ALL_KNOWN = {'Physical', 'Special', 'Damage', 'Faint'}
    other = [n for n in slot_names
             if not any(cat in n for cat in _ALL_KNOWN)
             and n not in _DEFAULT_SLOTS]

    parts = []

    # Compact Physical + Special into an attack label
    if physical or special:
        if physical and special:
            parts.append('Attack')
        elif physical:
            parts.append('Physical')
        else:
            parts.append('Special')

    # Damage / Faint
    if damage and faint:
        parts.append('Faint')
    elif damage:
        parts.append('Damage' if len(damage) >= 2 else damage[0])
    elif faint:
        parts.append('Faint')

    # Remaining non-defaulting slots (Idle 2-5, Special, etc.)
    parts.extend(other)

    return ' + '.join(parts) if parts else slot_names[0]


def _walk_parallel(anim_joint, joint, tracks, loop_flag,
                   joint_to_bone_index, bones, logger, options=None):
    """Walk AnimationJoint and Joint trees in parallel, decoding keyframes."""
    bone_index = joint_to_bone_index.get(joint.address, 0)
    bone = bones[bone_index]

    if anim_joint.animation:
        aobj = anim_joint.animation

        if not (aobj.flags & AOBJ_NO_ANIM):
            track = _describe_bone_track(aobj, joint, bone, bone_index, bones, logger, options)
            if track is not None:
                tracks.append(track)
                is_loop = bool(aobj.flags & AOBJ_ANIM_LOOP)
                loop_flag[0] = loop_flag[0] or is_loop

    if anim_joint.child and joint.child:
        _walk_parallel(anim_joint.child, joint.child, tracks, loop_flag,
                       joint_to_bone_index, bones, logger, options)
    if anim_joint.next and joint.next:
        _walk_parallel(anim_joint.next, joint.next, tracks, loop_flag,
                       joint_to_bone_index, bones, logger, options)


def _decode_bone_channels(aobj, joint=None, bone=None, bones=None,
                          logger=None, options=None):
    """Walk the Fobj chain on `aobj` and decode keyframes per channel.

    Pure: returns the decoded channel data without composing the rest matrix
    or constructing an IRBoneTrack. Translation keyframes are scaled from GC
    units to meters here so callers see consistent units.

    `joint`, `bone`, and `bones` are only consulted when an HSD_A_J_PATH
    channel is present (spline path needs the bone hierarchy for world
    positioning); they may be None for plain SRT-only tracks.

    Returns:
        (rotation, location, scale, spline_path) where rotation/location/scale
        are each a length-3 list of IRKeyframe lists (X, Y, Z), and
        spline_path is an IRSplinePath or None.
    """
    rotation = [[], [], []]
    location = [[], [], []]
    scale = [[], [], []]
    spline_path = None

    fobj = aobj.frame
    while fobj:
        if fobj.type == HSD_A_J_PATH:
            if joint is not None and bone is not None and bones is not None:
                spline_path = _extract_spline_path(aobj, joint, bone, bones, fobj, logger, options)

        elif fobj.type in _CHANNEL_MAP:
            category, component = _CHANNEL_MAP[fobj.type]
            keyframes = decode_fobjdesc(fobj, logger=logger, options=options)

            if category == 'r':
                rotation[component] = keyframes
            elif category == 'l':
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
                location[component] = keyframes
            elif category == 's':
                scale[component] = keyframes

        fobj = fobj.next

    return rotation, location, scale, spline_path


def _describe_bone_track(aobj, joint, bone, bone_index, bones, logger=None, options=None):
    """Decode all channels for one bone into an IRBoneTrack."""
    rotation, location, scale, spline_path = _decode_bone_channels(
        aobj, joint, bone, bones, logger=logger, options=options,
    )

    if spline_path and logger:
        logger.info("  PATH bone '%s' (idx=%d): %d param kf, %d control pts (type=%d)",
                    bone.name, bone_index, len(spline_path.parameter_keyframes),
                    len(spline_path.control_points), spline_path.curve_type)

    # Compute the rest-pose local matrix as plain T @ R @ S (no parent_scl
    # correction). The animated matrix in Phase 5 also uses plain T @ R @ S,
    # so they cancel at rest (identity). Blender's ALIGNED inheritance handles
    # parent scale propagation at evaluation time.
    #
    # The parent_scl correction from HSD's aligned scale inheritance is NOT
    # applied here because it creates shear in the matrix. TRS decomposition
    # can't represent shear, causing cascading errors in deep bone chains.
    #
    # Near-zero guard: bones hidden at rest (scale ≈ 0) use a "visible scale"
    # discovered by scanning animation keyframes.
    rest_scale = tuple(joint.scale)
    nz = 0.001
    if any(abs(rest_scale[c]) < nz for c in range(3)):
        vis = _find_visible_scale_in_channels(scale)
        use_scale = vis if vis is not None else rest_scale
    else:
        use_scale = rest_scale

    scaled_pos = tuple(p * GC_TO_METERS for p in joint.position)
    rest_local = compile_srt_matrix(use_scale, joint.rotation, scaled_pos)

    return IRBoneTrack(
        bone_name=bone.name,
        bone_index=bone_index,
        rotation=rotation,
        location=location,
        scale=scale,
        rest_local_matrix=matrix_to_list(rest_local),
        rest_rotation=tuple(joint.rotation),
        rest_position=scaled_pos,
        rest_scale=rest_scale,
        end_frame=aobj.end_frame,
        spline_path=spline_path,
    )


def _find_visible_scale_in_channels(scale_channels):
    """Find a non-zero scale from animation keyframes for a near-zero rest bone.

    Args:
        scale_channels: list of 3 keyframe lists [X, Y, Z] for scale.

    Returns:
        (sx, sy, sz) tuple if a visible scale was found, else None.
    """
    nz = 0.001
    best = [None, None, None]
    for ch in range(3):
        for kf in scale_channels[ch]:
            if abs(kf.value) >= nz:
                if best[ch] is None:
                    best[ch] = kf.value
    if all(v is not None for v in best):
        return tuple(best)
    return None


def _extract_spline_path(aobj, joint, bone, bones, fobj, logger, options=None):
    """Extract spline path data from a PATH animation channel into IRSplinePath."""
    path_keyframes = decode_fobjdesc(fobj, logger=logger, options=options)
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

    control_points = [[c * GC_TO_METERS for c in p] for p in spline_node.s1]
    curve_type = getattr(spline_node, 'flags', 0) >> 8
    tension = getattr(spline_node, 'f0', 0.0) or 0.0
    num_cvs = getattr(spline_node, 'n', 0)

    # Compute world matrix for the spline joint (for curve positioning)
    world_matrix = None
    if spline_joint:
        scaled_spl_pos = tuple(p * GC_TO_METERS for p in spline_joint.position)
        spline_local = compile_srt_matrix(
            spline_joint.scale, spline_joint.rotation, scaled_spl_pos
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
