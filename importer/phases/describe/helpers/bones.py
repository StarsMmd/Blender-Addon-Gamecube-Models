"""Describe Joint tree as a flat list of IRBone dataclasses.

Ports the pure-data computation from Joint.buildBoneHierarchy() and
Joint.compileSRTMatrix(), producing IRBone instances without any bpy calls.
"""
try:
    from .....shared.helpers.math_shim import Matrix, Vector, Euler, compile_srt_matrix, matrix_to_list
    from .....shared.IR.skeleton import IRBone
    from .....shared.IR.enums import ScaleInheritance
    from .....shared.Constants.hsd import (
        JOBJ_HIDDEN, JOBJ_INSTANCE, JOBJ_EFFECTOR, JOBJ_SPLINE,
        JOBJ_TYPE_MASK, JOBJ_CLASSICAL_SCALING, JOBJ_USE_QUATERNION,
        JOBJ_BILLBOARD_FIELD, JOBJ_BILLBOARD, JOBJ_VBILLBOARD,
        JOBJ_HBILLBOARD, JOBJ_RBILLBOARD,
    )
    from .....shared.helpers.scale import GC_TO_METERS
except (ImportError, SystemError):
    from shared.helpers.math_shim import Matrix, Vector, Euler, compile_srt_matrix, matrix_to_list
    from shared.IR.skeleton import IRBone
    from shared.IR.enums import ScaleInheritance
    from shared.helpers.scale import GC_TO_METERS
    from shared.Constants.hsd import (
        JOBJ_HIDDEN, JOBJ_INSTANCE, JOBJ_EFFECTOR, JOBJ_SPLINE,
        JOBJ_TYPE_MASK, JOBJ_CLASSICAL_SCALING, JOBJ_USE_QUATERNION,
        JOBJ_BILLBOARD_FIELD, JOBJ_BILLBOARD, JOBJ_VBILLBOARD,
        JOBJ_HBILLBOARD, JOBJ_RBILLBOARD,
    )


def describe_bones(root_joint, options=None, logger=None):
    """Walk a Joint tree and produce a flat list of IRBone.

    Args:
        root_joint: Root Joint node from the parsed node tree.
        options: dict of importer options (uses 'ik_hack').
        logger: optional Logger instance.

    Returns:
        (list[IRBone], dict[int, int]) — bones list and joint_address→bone_index map.
    """
    if options is None:
        options = {}

    bones = []
    joint_to_bone_index = {}
    bone_count = [0]  # mutable counter for closure

    # Pre-count total bones to determine digit padding
    def _count_joints(joint):
        n = 1
        if joint.child and not (joint.flags & (1 << 12)):
            n += _count_joints(joint.child)
        if joint.next:
            n += _count_joints(joint.next)
        return n
    total_bones = _count_joints(root_joint)
    bone_digits = len(str(max(total_bones - 1, 0)))

    # Build bone_index → body map suffix from PKX header
    _body_map_suffixes = {}
    pkx_header = options.get("pkx_header") if options else None
    if pkx_header and pkx_header.anim_entries:
        _NJ_LABELS = [
            "Root", "Head", "Center", "Body3", "Neck", "HeadTop",
            "LimbL", "LimbR", "Sec8", "Sec9", "Sec10", "Sec11",
            "AttachA", "AttachB", "AttachC", "AttachD",
        ]
        # Count how many body map fields reference each bone index
        bone_ref_counts = {}
        first_entry = pkx_header.anim_entries[0]
        for j in range(16):
            idx = first_entry.body_map_bones[j]
            if idx >= 0:
                bone_ref_counts.setdefault(idx, []).append(_NJ_LABELS[j])
        # Suffix bones referenced by exactly one field, but always
        # suffix the root bone regardless of how many fields reference it.
        for idx, labels in bone_ref_counts.items():
            if "Root" in labels:
                _body_map_suffixes[idx] = "Root"
            elif len(labels) == 1:
                _body_map_suffixes[idx] = labels[0]

    def _walk(joint, parent_index, parent_data):
        """Recursively describe a Joint and its children/siblings.

        parent_data is the transform record returned by
        _compose_bone_transforms for the parent bone — or None for roots.
        """
        my_index = len(bones)
        joint_to_bone_index[joint.address] = my_index

        idx = bone_count[0]
        name = 'Bone_%s' % str(idx).zfill(bone_digits)
        suffix = _body_map_suffixes.get(idx)
        if suffix:
            name = '%s_%s' % (name, suffix)
        bone_count[0] += 1

        # Warn about special JOBJ flags that we preserve but don't fully handle.
        if logger:
            if joint.flags & JOBJ_USE_QUATERNION:
                logger.info("  WARNING: %s has JOBJ_USE_QUATERNION flag (0x%X) — "
                            "rotation may be incorrect if stored as quaternion",
                            name, joint.flags)
            billboard_type = joint.flags & JOBJ_BILLBOARD_FIELD
            if billboard_type:
                bb_names = {
                    JOBJ_BILLBOARD: 'BILLBOARD', JOBJ_VBILLBOARD: 'VBILLBOARD',
                    JOBJ_HBILLBOARD: 'HBILLBOARD', JOBJ_RBILLBOARD: 'RBILLBOARD',
                }
                logger.info("  INFO: %s has billboard flag: %s (camera-dependent, not visualized)",
                            name, bb_names.get(billboard_type, hex(billboard_type)))

        # Determine IK shrink
        ik_shrink = bool(
            options.get("ik_hack")
            and ((joint.flags & JOBJ_TYPE_MASK) == JOBJ_EFFECTOR
                 or joint.flags & JOBJ_SPLINE)
        )

        scaled_position = tuple(p * GC_TO_METERS for p in joint.position)
        record = _compose_bone_transforms(
            joint.scale, joint.rotation, scaled_position,
            bool(joint.flags & JOBJ_CLASSICAL_SCALING),
            parent_data,
        )

        # Get inverse bind matrix if present, scaling translation to meters
        inverse_bind = None
        if hasattr(joint, 'inverse_bind') and joint.inverse_bind is not None:
            inv = joint.inverse_bind
            if hasattr(inv, 'to_list'):
                inverse_bind = inv.to_list()
            elif isinstance(inv, (list, tuple)):
                inverse_bind = [list(row) for row in inv]
            else:
                inverse_bind = [[inv[i][j] for j in range(4)] for i in range(4)]
            # Scale translation column (column 3, rows 0-2) to meters
            for row in range(3):
                inverse_bind[row][3] *= GC_TO_METERS

        bone = IRBone(
            name=name,
            parent_index=parent_index,
            position=scaled_position,
            rotation=tuple(joint.rotation),
            scale=tuple(joint.scale),
            inverse_bind_matrix=inverse_bind,
            flags=joint.flags,
            is_hidden=bool(joint.flags & JOBJ_HIDDEN),
            inherit_scale=ScaleInheritance.ALIGNED,
            ik_shrink=ik_shrink,
            world_matrix=matrix_to_list(record['world']),
            local_matrix=matrix_to_list(record['local']),
            normalized_world_matrix=matrix_to_list(record['normalized_world']),
            normalized_local_matrix=matrix_to_list(record['normalized_local']),
            scale_correction=matrix_to_list(record['scale_correction']),
            accumulated_scale=record['accumulated_scale'],
        )
        bones.append(bone)

        # Data passed to children (same shape as _compose_bone_transforms input)
        my_data = record

        # Recurse into children (skip instances)
        if joint.child and not (joint.flags & JOBJ_INSTANCE):
            _walk(joint.child, my_index, my_data)

        # Recurse into siblings (same parent)
        if joint.next:
            _walk(joint.next, parent_index, parent_data)

    _walk(root_joint, None, None)

    # Set instance_child_bone_index for JOBJ_INSTANCE bones
    _set_instance_refs(root_joint, bones, joint_to_bone_index)

    return bones, joint_to_bone_index


def _set_instance_refs(joint, bones, jtb):
    """Set instance_child_bone_index for JOBJ_INSTANCE bones."""
    if joint.flags & JOBJ_INSTANCE and joint.child:
        my_idx = jtb.get(joint.address)
        child_idx = jtb.get(joint.child.address)
        if my_idx is not None and child_idx is not None:
            bones[my_idx].instance_child_bone_index = child_idx
    if joint.child and not (joint.flags & JOBJ_INSTANCE):
        _set_instance_refs(joint.child, bones, jtb)
    if joint.next:
        _set_instance_refs(joint.next, bones, jtb)


NEAR_ZERO_SCALE_EPSILON = 0.001


def _compose_bone_transforms(own_scale, rotation, position, classical_scaling, parent):
    """Compose the full bone transform record given parent state.

    Used by both the initial ``describe_bones`` pass and the ``fix_near_zero``
    rebind so the two stay numerically identical.

    Args:
        own_scale, rotation, position: this bone's SRT components.
        classical_scaling: True if JOBJ_CLASSICAL_SCALING is set — own scale
            then does NOT fold into the accumulated chain.
        parent: None for root, else a dict with keys ``accumulated_scale``,
            ``world`` (Matrix), ``normalized_world`` (Matrix),
            ``scale_correction`` (Matrix).

    Returns:
        dict with keys ``local``, ``world``, ``normalized_world``,
        ``normalized_local``, ``scale_correction``, ``accumulated_scale``.
    """
    parent_accum = parent['accumulated_scale'] if parent else None

    if parent_accum is None:
        accumulated = tuple(own_scale)
    elif classical_scaling:
        accumulated = tuple(parent_accum)
    else:
        accumulated = tuple(own_scale[c] * parent_accum[c] for c in range(3))

    local = compile_srt_matrix(own_scale, rotation, position, parent_accum)
    local_rot_only_inv = local.normalized().inverted()

    if parent is None:
        world = local
        normalized_world = world.normalized()
        normalized_local = normalized_world
        scale_correction = local_rot_only_inv @ local
    else:
        world = parent['world'] @ local
        normalized_world = world.normalized()
        normalized_local = parent['normalized_world'].inverted() @ normalized_world
        scale_correction = parent['scale_correction'] @ local_rot_only_inv @ local

    return {
        'local': local,
        'world': world,
        'normalized_world': normalized_world,
        'normalized_local': normalized_local,
        'scale_correction': scale_correction,
        'accumulated_scale': accumulated,
    }


def compute_model_visible_scales(bones, bone_animations):
    """Model-wide visible-scale table for near-zero-rest bones.

    For each bone whose rest scale has any component below the near-zero
    threshold, aggregate the maximum absolute scale value observed across
    every animation's keyframes on that bone. Missing per-channel data
    falls back to 1.0 so rest matrices are always invertible.

    Returns:
        dict[int, tuple[float, float, float]] keyed by bone index.
        Every near-zero bone is present in the result (no bone is left
        with a tiny rest scale that would later be inverted).
    """
    nz = NEAR_ZERO_SCALE_EPSILON

    near_zero = {
        i for i, bone in enumerate(bones)
        if any(abs(bone.scale[c]) < nz for c in range(3))
    }
    if not near_zero:
        return {}

    # Max absolute scale per channel across every animation.
    observed = {i: [0.0, 0.0, 0.0] for i in near_zero}
    for anim_set in bone_animations:
        for track in anim_set.tracks:
            if track.bone_index not in near_zero:
                continue
            row = observed[track.bone_index]
            for ch in range(3):
                for kf in track.scale[ch]:
                    mag = abs(kf.value)
                    if mag >= nz and mag > row[ch]:
                        row[ch] = mag

    # Per-channel fallback to 1.0 where no animation revealed a visible value.
    # Keep the sign of the original rest scale when available (preserves
    # handedness) but never let magnitude go below 1.0.
    visible_scales = {}
    for i, row in observed.items():
        rest = bones[i].scale
        resolved = []
        for ch in range(3):
            if row[ch] >= nz:
                sign = -1.0 if rest[ch] < 0 else 1.0
                resolved.append(sign * row[ch])
            else:
                resolved.append(1.0 if rest[ch] >= 0 else -1.0)
        visible_scales[i] = tuple(resolved)
    return visible_scales


def fix_near_zero_bone_matrices(bones, bone_animations, logger=None):
    """Rebind world matrices for bones with near-zero rest scale.

    Tiny rest scales can't be cleanly inverted during mesh skinning or
    pose-basis computation. For every near-zero bone we substitute a
    "visible scale" (max absolute value observed across all animations,
    falling back to 1.0) and cascade corrected world matrices to all
    descendants. The animation basis naturally collapses descendants back
    to zero at hidden frames because basis = animated / visible.

    Must run AFTER describe_bones and describe_bone_animations, and BEFORE
    describe_meshes — mesh vertices bake into bone world frames, so the
    rebind has to finish first or verts end up in the pre-rebind frame.

    Args:
        bones: list[IRBone] — mutated in-place.
        bone_animations: list[IRBoneAnimationSet] from describe_bone_animations.
        logger: optional Logger instance.
    """
    visible_scales = compute_model_visible_scales(bones, bone_animations)
    if not visible_scales:
        return

    # Rewrite each track's rest_local_matrix to the same model-wide visible
    # scale, so animations that keep the bone hidden throughout still get a
    # stable (invertible) rest for basis computation.
    for anim_set in bone_animations:
        for track in anim_set.tracks:
            vis = visible_scales.get(track.bone_index)
            if vis is None:
                continue
            rest_local = compile_srt_matrix(vis, track.rest_rotation, track.rest_position)
            track.rest_local_matrix = matrix_to_list(rest_local)

    # Descendant cascade: subtree under any rebound bone needs world recomputation.
    needs_recompute = set(visible_scales)
    for i, bone in enumerate(bones):
        if bone.parent_index in needs_recompute:
            needs_recompute.add(i)

    if logger:
        logger.debug("  fix_near_zero_bone_matrices: %d rebound, %d descendants",
                     len(visible_scales), len(needs_recompute) - len(visible_scales))

    # Top-down rebuild: descendants' local_matrix was computed with the
    # aligned-scale correction against the original tiny accumulated parent
    # scale (dividing by tiny → huge local entries), so we have to rebuild
    # the full transform record, not just the world matrix. Walking in DFS
    # order (parent before child) means `rebound[parent]` is already set
    # when we reach a child; bones outside `needs_recompute` fall through
    # the `_parent_record` helper to their pre-rebind stored values.
    rebound = {}  # bone_index → transform record from _compose_bone_transforms

    def _parent_record(parent_index):
        if parent_index is None:
            return None
        if parent_index in rebound:
            return rebound[parent_index]
        p = bones[parent_index]
        return {
            'accumulated_scale': p.accumulated_scale,
            'world': Matrix(p.world_matrix),
            'normalized_world': Matrix(p.normalized_world_matrix),
            'scale_correction': Matrix(p.scale_correction),
        }

    for i in range(len(bones)):
        if i not in needs_recompute:
            continue
        bone = bones[i]

        own_scale = visible_scales[i] if i in visible_scales else bone.scale
        record = _compose_bone_transforms(
            own_scale, bone.rotation, bone.position,
            bool(bone.flags & JOBJ_CLASSICAL_SCALING),
            _parent_record(bone.parent_index),
        )

        bone.local_matrix = matrix_to_list(record['local'])
        bone.world_matrix = matrix_to_list(record['world'])
        bone.normalized_world_matrix = matrix_to_list(record['normalized_world'])
        bone.normalized_local_matrix = matrix_to_list(record['normalized_local'])
        bone.scale_correction = matrix_to_list(record['scale_correction'])
        bone.accumulated_scale = record['accumulated_scale']
        rebound[i] = record

        if i in visible_scales and logger:
            logger.leniency("near_zero_bone_rescued",
                            "Bone_%d (%s): rest scale near zero, rescued with visible scale %s",
                            i, bone.name, visible_scales[i])
