"""Build Blender bone animations from IRBoneAnimationSet.

Reads generic decoded keyframes from the IR and performs Blender-specific
baking: inserts into temp fcurves, samples frame-by-frame with scale
correction, decomposes to bone-local Euler, creates final Actions.
"""
import math
import bpy
from mathutils import Matrix, Vector

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
            _bake_bone_track(track, action, bone_data, max_frame, logger, armature)

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

            for mat_track in anim_set.material_tracks:
                mat = material_lookup.get(mat_track.material_mesh_name)
                logger.debug("    MatTrack lookup: '%s' → %s", mat_track.material_mesh_name, mat.name if mat else 'NOT FOUND')
                if not mat:
                    continue

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

        # Detect static poses
        is_static = True
        for fcurve in action.fcurves:
            if len(fcurve.keyframe_points) > 1:
                first_val = fcurve.keyframe_points[0].co[1]
                for kp in fcurve.keyframe_points:
                    if abs(kp.co[1] - first_val) > 1e-6:
                        is_static = False
                        break
            if not is_static:
                break

        if is_static:
            action.name = anim_set.name.replace('Anim', 'Pose')

        actions.append(action)
        logger.info("  Action '%s': %d bone fcurves, %d material fcurves, static=%s",
                    action.name, len(action.fcurves), mat_fcurve_count, is_static)

        bpy.ops.object.mode_set(mode='OBJECT')

    # Reset pose to rest position — the new pipeline's edit bones encode
    # the rest pose, so zeroing pose transforms gives the correct rest shape.
    # This is specific to how Phase 5 builds bones and does not apply to
    # legacy-built armatures.
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode='POSE')
    for bone in armature.pose.bones:
        bone.location = (0, 0, 0)
        bone.rotation_euler = (0, 0, 0)
        bone.rotation_quaternion = (1, 0, 0, 0)
        bone.scale = (1, 1, 1)
    bpy.ops.object.mode_set(mode='OBJECT')

    return actions, mat_slot_indices


def _bake_bone_track(track, action, bone_data, max_frame, logger, armature=None):
    """Bake one bone's IRBoneTrack into Blender fcurves."""
    bone_name = track.bone_name
    bone_idx = track.bone_index
    bd = bone_data[bone_idx]
    parent_idx = bd['parent_index']

    has_path = track.spline_path is not None

    # Path animation: create a Blender curve and FOLLOW_PATH constraint.
    # SRT baking continues below — LIMIT_LOCATION zeroes the baked location
    # at runtime, but rotation/scale from SRT baking still take effect.
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

                # Apply bezier handles after all points are inserted
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

    # Pre-fetch Blender-specific matrices
    local_edit_matrix = bd['local_edit_matrix']
    edit_scale_correction = bd['edit_scale_correction']
    temp_matrix_local = bd['temp_matrix_local']
    parent_edit_scale_correction = (
        bone_data[parent_idx]['edit_scale_correction'] if parent_idx is not None else None
    )
    # Note: parent_scl is NOT passed to compile_srt_matrix during animation baking.
    # The aligned scale inheritance correction is already accounted for by the
    # edit_scale_correction matrices. Legacy compileSRTMatrix is called with only
    # 3 args (no parent_scl) during animation — matching this behavior.

    # Pass 2: frame-by-frame baking with scale correction
    end_frame = min(int(track.end_frame), max_frame)

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

        # Path bones: the curve is in unrotated GameCube space while the
        # armature has a π/2 X rotation. This rotation on the SRT matrix
        # compensates so the walk animation aligns with the path direction.
        if has_path:
            mtx = Matrix.Rotation(-math.pi / 2, 4, 'X') @ mtx

        try:
            if parent_idx is not None:
                Bmtx = (local_edit_matrix.inverted()
                        @ parent_edit_scale_correction
                        @ mtx
                        @ edit_scale_correction.inverted())
            else:
                Bmtx = (local_edit_matrix.inverted()
                        @ mtx
                        @ edit_scale_correction.inverted())
        except ValueError:
            # Singular matrix — bone has zero/near-zero scale. Use safe fallback.
            logger.debug("  %s: singular matrix at frame %d, using fallback", bone_name, frame)
            Bmtx = temp_matrix_local.inverted_safe() @ mtx

        trans, rot, scl = Bmtx.decompose()
        rot = rot.to_euler()

        if frame <= 3 or frame == end_frame - 1:
            logger.info("  BAKE %s f=%d loc=(%.6f,%.6f,%.6f) rot=(%.6f,%.6f,%.6f) scl=(%.6f,%.6f,%.6f)",
                        bone_name, frame, trans[0], trans[1], trans[2], rot[0], rot[1], rot[2], scl[0], scl[1], scl[2])
        if frame == 0:
            logger.info("  SRT_BAKE bone=%s frame=0 uses_path=%s", bone_name, has_path)
            logger.info("    srt_in: r=(%.6f,%.6f,%.6f) l=(%.6f,%.6f,%.6f) s=(%.6f,%.6f,%.6f)",
                        r[0], r[1], r[2], l[0], l[1], l[2], s[0], s[1], s[2])
            logger.info("    blender_out: loc=(%.6f,%.6f,%.6f) rot=(%.6f,%.6f,%.6f) scl=(%.6f,%.6f,%.6f)",
                        trans[0], trans[1], trans[2], rot[0], rot[1], rot[2], scl[0], scl[1], scl[2])
            logger.info("    local_edit_matrix[0]=%s", [round(local_edit_matrix[i][0], 6) for i in range(4)])
            logger.info("    has_parent=%s", parent_idx is not None)

        max_scl = 100.0
        scl = Vector((
            max(-max_scl, min(max_scl, scl[0])),
            max(-max_scl, min(max_scl, scl[1])),
            max(-max_scl, min(max_scl, scl[2])),
        ))

        new_transform_list[0].keyframe_points.insert(frame, rot[0]).interpolation = 'BEZIER'
        new_transform_list[1].keyframe_points.insert(frame, rot[1]).interpolation = 'BEZIER'
        new_transform_list[2].keyframe_points.insert(frame, rot[2]).interpolation = 'BEZIER'
        new_transform_list[4].keyframe_points.insert(frame, trans[0]).interpolation = 'BEZIER'
        new_transform_list[5].keyframe_points.insert(frame, trans[1]).interpolation = 'BEZIER'
        new_transform_list[6].keyframe_points.insert(frame, trans[2]).interpolation = 'BEZIER'
        new_transform_list[7].keyframe_points.insert(frame, scl[0]).interpolation = 'BEZIER'
        new_transform_list[8].keyframe_points.insert(frame, scl[1]).interpolation = 'BEZIER'
        new_transform_list[9].keyframe_points.insert(frame, scl[2]).interpolation = 'BEZIER'

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
