"""Build Blender bone animations from IRBoneAnimationSet.

Reads generic decoded keyframes from the IR and performs Blender-specific
baking: inserts into temp fcurves, samples frame-by-frame with scale
correction, decomposes to bone-local Euler, creates final Actions.
"""
import math
import bpy
from mathutils import Matrix, Vector, Euler, Quaternion

try:
    from .....shared.Constants.hsd import *
    from .....shared.helpers.logger import StubLogger
    from .....shared.BlenderVersion import BlenderVersion
except (ImportError, SystemError):
    from shared.Constants.hsd import *
    from shared.helpers.logger import StubLogger
    from shared.BlenderVersion import BlenderVersion

try:
    from .....shared.helpers.math_shim import compile_srt_matrix
except (ImportError, SystemError):
    from shared.helpers.math_shim import compile_srt_matrix


def build_bone_animations(ir_model, armature, options, logger=StubLogger(), material_lookup=None):
    """Create Blender Actions from IRBoneAnimationSet list.

    Each Action contains an OBJECT slot for bone fcurves, plus MATERIAL slots
    for any paired material animation tracks (unified multi-slot actions).

    Args:
        ir_model: IRModel with bone_animations and bones populated.
        armature: Blender armature object.
        options: importer options dict.
        logger: Logger instance.
        material_lookup: dict mapping mesh_name → bpy.types.Material (for material animations).
    """
    from .material_animations import apply_color_tracks, apply_texture_uv_tracks

    max_frame = options.get("max_frame", 1000)
    bone_data = _build_bone_data_lookup(ir_model.bones)
    actions = []
    mat_slot_indices = {}  # {material: slot_index_in_action}

    for anim_set in ir_model.bone_animations:
        action = bpy.data.actions.new(anim_set.name)
        action.use_fake_user = True

        armature_slot = action.slots.new('OBJECT', 'Armature')
        action.slots.active = armature_slot

        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode='POSE')

        for bone in armature.pose.bones:
            bone.rotation_mode = 'XYZ'
        for bone in armature.data.bones:
            bone.use_local_location = True

        armature.animation_data_create()
        armature.animation_data.action = action
        armature.animation_data.action_slot = armature_slot

        for track in anim_set.tracks:
            _bake_bone_track(track, action, bone_data, ir_model.bones,
                             max_frame, logger, armature)

        # Build paired material animation tracks into the same action
        # using channelbag API so fcurves are associated with the correct slot
        mat_fcurve_count = 0
        if anim_set.material_tracks and material_lookup:
            # Get the existing layer/strip, or create one if no bone tracks exist
            # (e.g. material-only animations like water UV scrolling)
            if action.layers:
                layer = action.layers[0]
                strip = layer.strips[0]
            else:
                layer = action.layers.new("Layer")
                strip = layer.strips.new(type='KEYFRAME')

            animated_materials = set()  # skip duplicates from shared materials
            for mat_track in anim_set.material_tracks:
                mat = material_lookup.get(mat_track.material_mesh_name)
                logger.debug("    MatTrack lookup: '%s' → %s", mat_track.material_mesh_name, mat.name if mat else 'NOT FOUND')
                if not mat:
                    continue
                if id(mat) in animated_materials:
                    logger.debug("    MatTrack '%s': skipping (material '%s' already animated)",
                                 mat_track.material_mesh_name, mat.name)
                    continue
                animated_materials.add(id(mat))

                # Create a MATERIAL slot and its channelbag in the same action
                mat_slot = action.slots.new('MATERIAL', mat.name or 'Material')
                channelbag = strip.channelbag(mat_slot, ensure=True)

                # Temporarily assign so Blender can resolve the slot
                if not mat.animation_data:
                    mat.animation_data_create()
                mat.animation_data.action = action
                mat.animation_data.action_slot = mat_slot

                before = len(channelbag.fcurves)
                apply_color_tracks(mat_track, mat, channelbag.fcurves, max_frame, logger)
                apply_texture_uv_tracks(mat_track, mat, channelbag.fcurves, logger)
                mat_fcurve_count += len(channelbag.fcurves) - before

                # All actions use the same slot layout, so record the index once
                if mat not in mat_slot_indices:
                    mat_slot_indices[mat] = len(action.slots) - 1

            # Restore armature slot as active
            action.slots.active = armature_slot

        actions.append(action)
        logger.info("  Action '%s': %d bone fcurves, %d material fcurves",
                    action.name, len(action.fcurves), mat_fcurve_count)

        bpy.ops.object.mode_set(mode='OBJECT')

    return actions, mat_slot_indices


def reset_pose(armature):
    """Reset all pose bones to rest position.

    The new pipeline's edit bones encode the rest pose, so zeroing pose
    transforms gives the correct rest shape. Must run after skeleton build,
    regardless of whether animations exist.

    Uses direct property assignment instead of mode-switching operators,
    which are fragile when prior imports leave Blender in unexpected state.
    """
    for bone in armature.pose.bones:
        bone.location = (0, 0, 0)
        bone.rotation_euler = (0, 0, 0)
        bone.rotation_quaternion = (1, 0, 0, 0)
        bone.scale = (1, 1, 1)


def _bake_bone_track(track, action, bone_data, bones, max_frame, logger, armature=None):
    """Bake one bone's IRBoneTrack into Blender fcurves.

    Hybrid formula based on parent scale uniformity:
    - Uniform: legacy formula with edit_scale_correction (correct for ALIGNED inheritance)
    - Non-uniform: direct SRT delta (avoids shear from TRS decomposition)
    """
    bone_name = track.bone_name
    bone_idx = track.bone_index
    bd = bone_data[bone_idx]
    parent_idx = bd['parent_index']

    # Determine bake strategy based on accumulated scale uniformity
    accum = bones[bone_idx].accumulated_scale
    mn = min(abs(x) for x in accum if abs(x) > 1e-6) if any(abs(x) > 1e-6 for x in accum) else 0
    mx = max(abs(x) for x in accum)
    use_legacy_formula = (mn > 0 and mx / max(mn, 1e-9) < 1.1)

    has_path = track.spline_path is not None

    if has_path and armature:
        _apply_path_constraint(track, action, armature, logger)

    # Pass 1: insert decoded IR keyframes into temporary fcurves
    TRANSFORM_COUNT = 10
    transform_list = [None] * TRANSFORM_COUNT

    channel_mapping = [
        (track.rotation, 'r', [0, 1, 2]),
        (track.location, 'l', [4, 5, 6]),
        (track.scale, 's', [7, 8, 9]),
    ]

    for channels, letter, indices in channel_mapping:
        for comp, idx in enumerate(indices):
            keyframes = channels[comp]
            if keyframes:
                data_path = 'pose.bones["%s"].%s' % (bone_name, letter)
                curve = action.fcurves.new(data_path, index=comp)
                for kf in keyframes:
                    point = curve.keyframe_points.insert(kf.frame, kf.value)
                    point.interpolation = kf.interpolation.value
                transform_list[idx] = curve

                kf_count = len(curve.keyframe_points)
                offset = kf_count - len(keyframes)
                for i, kf in enumerate(keyframes):
                    point = curve.keyframe_points[offset + i]
                    if kf.handle_left:
                        point.handle_left[:] = kf.handle_left
                    if kf.handle_right:
                        point.handle_right[:] = kf.handle_right

    # Fill missing channels with rest-pose constants
    rest = {
        'r': track.rest_rotation,
        'l': track.rest_position,
        's': track.rest_scale,
    }
    for channels, letter, indices in channel_mapping:
        for comp, idx in enumerate(indices):
            if not transform_list[idx]:
                data_path = 'pose.bones["%s"].%s' % (bone_name, letter)
                curve = action.fcurves.new(data_path, index=comp)
                curve.keyframe_points.insert(0, rest[letter][comp])
                transform_list[idx] = curve

    # Create final Blender fcurves
    new_transform_list = [None] * TRANSFORM_COUNT
    for i in range(3):
        new_transform_list[i] = action.fcurves.new(
            'pose.bones["%s"].rotation_euler' % bone_name, index=i)
        new_transform_list[i + 4] = action.fcurves.new(
            'pose.bones["%s"].location' % bone_name, index=i)
        new_transform_list[i + 7] = action.fcurves.new(
            'pose.bones["%s"].scale' % bone_name, index=i)

    # rest_local_matrix from IR: plain T@R@S with visible-scale correction
    # for near-zero bones. Path rotation applied symmetrically to both sides.
    rest_base = Matrix(track.rest_local_matrix)
    if has_path:
        rest_base = Matrix.Rotation(-math.pi / 2, 4, 'X') @ rest_base
    rest_base_inv = rest_base.inverted_safe()

    # Pre-compute rest SRT for the direct delta path
    rest_decomp = rest_base.decompose()
    rest_loc = rest_decomp[0]
    rest_s = rest_decomp[2]
    rest_quat = rest_decomp[1]
    rest_quat_inv = rest_quat.inverted()

    # For the legacy formula path: pre-fetch edit_scale_correction matrices
    if use_legacy_formula:
        local_edit = bd['local_edit_matrix']
        edit_sc = bd['edit_scale_correction']
        parent_edit_sc = (
            bone_data[parent_idx]['edit_scale_correction'] if parent_idx is not None else None
        )

    # Pass 2: frame-by-frame baking
    # Collect all baked values first, then batch-insert into fcurves.
    # This avoids O(frames × log(k)) per-frame insert overhead.
    end_frame = min(int(track.end_frame), max_frame)

    # Pre-allocate storage: 9 channels × end_frame values
    baked_values = [[] for _ in range(TRANSFORM_COUNT)]

    for frame in range(end_frame):
        s = [transform_list[7].evaluate(frame),
             transform_list[8].evaluate(frame),
             transform_list[9].evaluate(frame)]
        r = [transform_list[0].evaluate(frame),
             transform_list[1].evaluate(frame),
             transform_list[2].evaluate(frame)]
        l = [transform_list[4].evaluate(frame),
             transform_list[5].evaluate(frame),
             transform_list[6].evaluate(frame)]

        if frame <= 3 or frame == end_frame - 1:
            logger.info("  EVAL %s f=%d r=(%.6f,%.6f,%.6f) l=(%.6f,%.6f,%.6f) s=(%.6f,%.6f,%.6f)",
                        bone_name, frame, r[0], r[1], r[2], l[0], l[1], l[2], s[0], s[1], s[2])

        mtx = compile_srt_matrix(s, r, l)
        if has_path:
            mtx = Matrix.Rotation(-math.pi / 2, 4, 'X') @ mtx

        if use_legacy_formula:
            # Legacy formula: edit_scale_correction sandwich.
            # Correct for uniform parent scales (no shear). Encodes scale
            # information for ALIGNED inheritance propagation.
            try:
                if parent_idx is not None:
                    Bmtx = (local_edit.inverted()
                            @ parent_edit_sc
                            @ mtx
                            @ edit_sc.inverted())
                else:
                    Bmtx = (local_edit.inverted()
                            @ mtx
                            @ edit_sc.inverted())
            except ValueError:
                Bmtx = rest_base_inv @ mtx
            trans, rot, scl = Bmtx.decompose()
            rot = rot.to_euler()
        else:
            # Direct SRT delta: compute loc/rot/scl separately to avoid
            # shear contamination from non-uniform scale + rotation change.
            anim_loc = Vector((mtx[0][3], mtx[1][3], mtx[2][3]))
            delta_pos = anim_loc - rest_loc
            trans = delta_pos.copy()
            trans.rotate(rest_quat_inv)

            anim_quat = Euler((r[0], r[1], r[2]), 'XYZ').to_quaternion()
            if has_path:
                path_quat = Matrix.Rotation(-math.pi / 2, 4, 'X').to_quaternion()
                anim_quat = path_quat @ anim_quat
            rot = (rest_quat_inv @ anim_quat).to_euler('XYZ')

            scl = Vector((
                s[0] / rest_s[0] if abs(rest_s[0]) > 1e-6 else s[0],
                s[1] / rest_s[1] if abs(rest_s[1]) > 1e-6 else s[1],
                s[2] / rest_s[2] if abs(rest_s[2]) > 1e-6 else s[2],
            ))

        if frame <= 3 or frame == end_frame - 1:
            logger.info("  BAKE %s f=%d loc=(%.6f,%.6f,%.6f) rot=(%.6f,%.6f,%.6f) scl=(%.6f,%.6f,%.6f)",
                        bone_name, frame, trans[0], trans[1], trans[2], rot[0], rot[1], rot[2], scl[0], scl[1], scl[2])
        if frame == 0:
            logger.info("  SRT_BAKE bone=%s frame=0 uses_path=%s", bone_name, has_path)

        max_scl = 100.0
        scl = Vector((
            max(-max_scl, min(max_scl, scl[0])),
            max(-max_scl, min(max_scl, scl[1])),
            max(-max_scl, min(max_scl, scl[2])),
        ))

        baked_values[0].append((frame, rot[0]))
        baked_values[1].append((frame, rot[1]))
        baked_values[2].append((frame, rot[2]))
        baked_values[4].append((frame, trans[0]))
        baked_values[5].append((frame, trans[1]))
        baked_values[6].append((frame, trans[2]))
        baked_values[7].append((frame, scl[0]))
        baked_values[8].append((frame, scl[1]))
        baked_values[9].append((frame, scl[2]))

    # Batch-insert all keyframes: add() + bulk co/interpolation set is
    # much faster than per-frame insert() which shifts the internal array.
    for idx in [0, 1, 2, 4, 5, 6, 7, 8, 9]:
        curve = new_transform_list[idx]
        values = baked_values[idx]
        if not values:
            continue
        curve.keyframe_points.add(len(values))
        for i, (frame, value) in enumerate(values):
            kp = curve.keyframe_points[i]
            kp.co = (frame, value)
            kp.interpolation = 'BEZIER'

    # Remove temporary raw fcurves
    for c in transform_list:
        if c:
            action.fcurves.remove(c)


_SPLINE_TYPE_MAP = {
    0: 'POLY',
    2: 'NURBS',
}


def _apply_path_constraint(track, action, armature, logger):
    """Create a Blender curve from spline points and add a FOLLOW_PATH constraint.

    Matches the main branch approach: the bone follows the curve via a constraint,
    and the path parameter is animated via the constraint's offset fcurve.
    """
    bone_name = track.bone_name
    path = track.spline_path
    points = path.control_points
    spline_type = path.curve_type
    num_cvs = path.num_control_points
    tension = path.tension

    # Create Blender curve object parented to the armature.
    # The armature has a π/2 X rotation, so parenting transforms the raw
    # GameCube Y-up curve coordinates to Blender Z-up automatically.
    curve_data = bpy.data.curves.new('path_' + bone_name, 'CURVE')
    curve_data.use_path = True
    curve_data.dimensions = '3D'
    curve_obj = bpy.data.objects.new('Path_' + bone_name, curve_data)
    curve_obj.parent = armature
    # Position curve at the spline joint's location in the armature
    if path.world_matrix:
        curve_obj.matrix_local = Matrix(path.world_matrix)
    bpy.context.scene.collection.objects.link(curve_obj)
    # Force Blender to recalculate world matrix after parenting
    bpy.context.view_layer.update()

    if spline_type == 0:
        # Linear spline
        spline = curve_data.splines.new('POLY')
        spline.points.add(len(points) - 1)
        for i, pt in enumerate(points):
            spline.points[i].co = (pt[0], pt[1], pt[2], 1.0)

    elif spline_type == 1:
        # Cubic bezier
        spline = curve_data.splines.new('BEZIER')
        spline.bezier_points.add(num_cvs - 1)
        for i in range(num_cvs):
            spline.bezier_points[i].co = points[3 * i]
            if i > 0:
                spline.bezier_points[i].handle_left = points[3 * (i - 1) + 2]
            if i < num_cvs - 1:
                spline.bezier_points[i].handle_right = points[3 * i + 1]

    elif spline_type == 2:
        # B-spline (NURBS in Blender)
        spline = curve_data.splines.new('NURBS')
        spline.points.add(len(points) - 1)
        spline.order_u = 4
        for i, pt in enumerate(points):
            spline.points[i].co = (pt[0], pt[1], pt[2], 1.0)

    elif spline_type == 3:
        # Cardinal spline → convert to bezier with computed handles
        spline = curve_data.splines.new('BEZIER')
        spline.bezier_points.add(num_cvs - 1)
        for i in range(num_cvs):
            cp = points[i + 1]  # cardinal CVs have +1 offset
            spline.bezier_points[i].co = cp
            if i > 0:
                p_prev = Vector(points[i])
                p_next = Vector(points[i + 2])
                spline.bezier_points[i].handle_left = (Vector(cp) - tension / 3.0 * (p_next - p_prev))[:]
            if i < num_cvs - 1:
                p_prev = Vector(points[i])
                p_next = Vector(points[i + 2])
                spline.bezier_points[i].handle_right = (Vector(cp) + tension / 3.0 * (p_next - p_prev))[:]

    else:
        logger.info("  PATH %s: unsupported spline type %d", bone_name, spline_type)
        return

    # Add FOLLOW_PATH constraint (already in POSE mode from caller)
    pose_bone = armature.pose.bones[bone_name]

    path_constr = pose_bone.constraints.new('FOLLOW_PATH')
    # Move constraint to top so it's evaluated first
    pose_bone.constraints.move(len(pose_bone.constraints) - 1, 0)
    path_constr.target = curve_obj

    # Zero out bone's local translation so position comes entirely from
    # FOLLOW_PATH. The SRT baking still produces location keyframes but
    # LIMIT_LOCATION overrides them at runtime. Rotation/scale still apply.
    limit_constr = pose_bone.constraints.new('LIMIT_LOCATION')
    pose_bone.constraints.move(len(pose_bone.constraints) - 1, 0)
    for axis in ['x', 'y', 'z']:
        setattr(limit_constr, 'use_min_' + axis, True)
        setattr(limit_constr, 'use_max_' + axis, True)
        setattr(limit_constr, 'min_' + axis, 0.0)
        setattr(limit_constr, 'max_' + axis, 0.0)

    # Animate constraint offset with path parameter keyframes
    # Scale: normalized (0-1) → negative path duration (Blender convention)
    path_duration = curve_data.path_duration
    data_path = 'pose.bones["%s"].constraints["%s"].offset' % (bone_name, path_constr.name)
    offset_curve = action.fcurves.new(data_path)
    for kf in path.parameter_keyframes:
        scaled_value = kf.value * -path_duration
        point = offset_curve.keyframe_points.insert(kf.frame, scaled_value)
        point.interpolation = kf.interpolation.value
    # Apply bezier handles (scaled)
    kf_count = len(offset_curve.keyframe_points)
    kf_offset = kf_count - len(path.parameter_keyframes)
    for i, kf in enumerate(path.parameter_keyframes):
        point = offset_curve.keyframe_points[kf_offset + i]
        if kf.handle_left:
            point.handle_left = (kf.handle_left[0], kf.handle_left[1] * -path_duration)
        if kf.handle_right:
            point.handle_right = (kf.handle_right[0], kf.handle_right[1] * -path_duration)

    logger.info("  PATH_SETUP bone=%s curve_obj=%s path_duration=%d", bone_name, curve_obj.name, path_duration)
    logger.info("    curve_world_matrix=%s", [list(row) for row in curve_obj.matrix_world])
    logger.info("    curve_parent=%s", curve_obj.parent.name if curve_obj.parent else 'None')
    logger.info("    offset_kf_count=%d", len(offset_curve.keyframe_points))
    if len(offset_curve.keyframe_points) > 0:
        logger.info("    offset_kf[0]=(%.4f, %.4f) offset_kf[-1]=(%.4f, %.4f)",
                    offset_curve.keyframe_points[0].co[0], offset_curve.keyframe_points[0].co[1],
                    offset_curve.keyframe_points[-1].co[0], offset_curve.keyframe_points[-1].co[1])
    for si, sp in enumerate(curve_data.splines):
        pt_count = len(sp.points) if sp.type != 'BEZIER' else len(sp.bezier_points)
        logger.info("    spline[%d] type=%s pts=%d", si, sp.type, pt_count)
        if sp.type != 'BEZIER':
            for pi in range(min(3, len(sp.points))):
                logger.info("      pt[%d]=(%.4f,%.4f,%.4f)", pi, sp.points[pi].co[0], sp.points[pi].co[1], sp.points[pi].co[2])
    logger.info("    constraints=[%s]", ', '.join('%s(%s)' % (c.type, c.name) for c in pose_bone.constraints))


def _build_bone_data_lookup(bones):
    """Build Blender-specific bone data for animation baking.

    Computes matrices from IRBone data needed for the scale correction
    formula. This is target-specific and belongs in Phase 5A.
    """
    lookup = {}
    for i, bone in enumerate(bones):
        lookup[i] = {
            'name': bone.name,
            'parent_index': bone.parent_index,
            'local_edit_matrix': Matrix(bone.normalized_local_matrix),
            'edit_scale_correction': Matrix(bone.scale_correction),
            'temp_matrix_local': Matrix(bone.local_matrix),
        }
    return lookup

