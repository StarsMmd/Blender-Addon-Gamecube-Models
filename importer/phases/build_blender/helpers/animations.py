"""Create Blender Actions from a BR action list.

Pure bpy executor for everything except the per-frame pose bake, which lives
in the Plan phase's ``bake_frame`` helper (pure math, no bpy) so it can be
unit-tested without a Blender runtime. This module only samples the raw
keyframe F-curves per frame, hands the whole chain's SRT to ``bake_frame``,
and writes the resulting shear-free loc/rot/scale basis back as F-curves.
"""
import math
import bpy
from mathutils import Matrix, Vector

try:
    from .....shared.helpers.logger import StubLogger
    from ...plan.helpers.animations import bake_frame, compute_bake_plan
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger
    from importer.phases.plan.helpers.animations import bake_frame, compute_bake_plan


def build_bone_animations(br_actions, armature, options, bake_skeleton,
                          logger=StubLogger(), material_lookup=None):
    """Create Blender Actions from a list of BRAction specs.

    Each Action gets an OBJECT slot named after the armature object plus
    MATERIAL slots for any paired material tracks (multi-slot actions).
    Naming the slot after its target follows Blender's own convention and
    gives the action a durable armature binding — the exporter's describe
    phase uses it to attach each action to the right armature in
    multi-model scenes.

    In: br_actions (list[BRAction]); armature (bpy.types.Object, armature);
        options (dict, reads 'max_frame'); bake_skeleton (BRBakeSkeleton,
        full-skeleton rest data driving the per-frame pose bake);
        logger (Logger); material_lookup (dict[str, bpy.types.Material]|None).
    Out: (list[bpy.types.Action], dict[bpy.types.Material, int]) — Actions in
         the order given + slot index map for material animations.
    """
    from .material_animations import apply_color_tracks, apply_texture_uv_tracks

    max_frame = options.get("max_frame", 1000)
    actions = []
    mat_slot_indices = {}

    for br_action in br_actions:
        action = bpy.data.actions.new(br_action.name)
        action.use_fake_user = True

        armature_slot = action.slots.new('OBJECT', armature.name)
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

        _bake_action(br_action.bone_tracks, action, max_frame, bake_skeleton,
                     logger, armature)

        mat_fcurve_count = _build_material_tracks(
            br_action, action, material_lookup, mat_slot_indices, max_frame,
            apply_color_tracks, apply_texture_uv_tracks, logger,
        )

        action.slots.active = armature_slot
        actions.append(action)
        logger.info("  Action '%s': %d bone fcurves, %d material fcurves",
                    action.name, len(action.fcurves), mat_fcurve_count)

        bpy.ops.object.mode_set(mode='OBJECT')

    return actions, mat_slot_indices


def reset_pose(armature):
    """Reset every pose bone to rest — zeros basis transforms.

    Direct property assignment (not mode-switching operators) so the reset
    is robust when prior imports leave Blender in unexpected state.

    In: armature (bpy.types.Object, armature; pose bones mutated in place).
    Out: None.
    """
    for bone in armature.pose.bones:
        bone.location = (0, 0, 0)
        bone.rotation_euler = (0, 0, 0)
        bone.rotation_quaternion = (1, 0, 0, 0)
        bone.scale = (1, 1, 1)


# ---------------------------------------------------------------------------
# Per-track bake — drives Blender fcurve interpolation, delegates math.
# ---------------------------------------------------------------------------

_CHANNEL_COUNT = 10
_ROT_INDICES = (0, 1, 2)
_LOC_INDICES = (4, 5, 6)
_SCL_INDICES = (7, 8, 9)


def _bake_action(bone_tracks, action, max_frame, bake_skeleton, logger, armature):
    """Bake one action into final loc/rot/scale fcurves.

    Every posed bone goes through one mechanism: Plan (``bake_frame``) composes
    its exact GX world for the frame and returns a mesh-correct *target* pose;
    build drops that target onto the pose bone (``pose_bone.matrix = target``)
    and reads back the resulting loc/rot/scale. The bone's ``inherit_scale``
    (ALIGNED for uniform un-animated-scale bones, NONE for the baked closure)
    only changes how Blender inverts the identical target — so the pose stays
    exact either way while ALIGNED bones keep sparse, inheritance-driven scale.
    Bones are posed depth-level by depth-level with a dependency-graph update
    between levels so each child inverts against its parent's freshly-posed
    matrix. Bones with no track but in the baked closure are posed too (their
    still pose must follow a scaled/animated ancestor). Path-constrained bones
    get a FOLLOW_PATH constraint instead.

    In: bone_tracks (list[BRBoneTrack]); action (bpy.types.Action, mutated);
        max_frame (int, upper bake bound); bake_skeleton (BRBakeSkeleton);
        logger (Logger); armature (bpy.types.Object|None, for FOLLOW_PATH).
    Out: None. Temporary raw fcurves are removed before returning.
    """
    path_indices = set()
    pose_tracks = []
    for track in bone_tracks:
        if track.spline_path is not None and armature is not None:
            _apply_path_constraint(track, action, armature, logger)
            path_indices.add(track.bone_index)
        else:
            pose_tracks.append(track)

    if not pose_tracks:
        return

    # Raw fcurves for every animated bone stay live for the whole frame loop
    # so we can sample the full chain's SRT at each frame.
    raw_by_bone = {}      # bone_index -> list[FCurve|None] (channel layout)
    end_by_bone = {}      # bone_index -> exclusive last frame for this bone
    for track in pose_tracks:
        raw = _insert_raw_keyframes(track, action)
        _fill_missing_channels_with_rest(track, action, raw)
        raw_by_bone[track.bone_index] = raw
        end_by_bone[track.bone_index] = min(int(track.end_frame), max_frame)

    global_end = max(end_by_bone.values())

    bake_indices, levels = compute_bake_plan(bake_skeleton, set(raw_by_bone))
    bake_indices = [i for i in bake_indices if i not in path_indices]
    levels = [[i for i in lvl if i not in path_indices] for lvl in levels]

    name_of = {i: bake_skeleton.bones[i].name for i in bake_indices}
    pose_bone_of = {i: armature.pose.bones[name_of[i]] for i in bake_indices}
    baked_by_bone = {i: [[] for _ in range(_CHANNEL_COUNT)] for i in bake_indices}

    # Detach the action while we drive the pose by hand: an assigned action
    # would re-evaluate on each depsgraph update and could clobber the matrices
    # we set. Raw-fcurve sampling (`fc.evaluate`) works detached.
    saved_action = armature.animation_data.action
    armature.animation_data.action = None

    for frame in range(global_end):
        frame_srts = {}
        for idx, raw in raw_by_bone.items():
            frame_srts[idx] = (
                (raw[7].evaluate(frame), raw[8].evaluate(frame), raw[9].evaluate(frame)),
                (raw[0].evaluate(frame), raw[1].evaluate(frame), raw[2].evaluate(frame)),
                (raw[4].evaluate(frame), raw[5].evaluate(frame), raw[6].evaluate(frame)),
            )
        targets = bake_frame(bake_skeleton, frame_srts, bake_indices)
        for level in levels:
            for idx in level:
                pose_bone = pose_bone_of[idx]
                pose_bone.matrix = Matrix(targets[idx])
                # matrix_basis (and loc/rot/scale) are set synchronously by the
                # matrix setter — read them back before the depsgraph update.
                if frame < end_by_bone.get(idx, global_end):
                    baked = baked_by_bone[idx]
                    euler = pose_bone.rotation_euler
                    loc = pose_bone.location
                    scale = pose_bone.scale
                    baked[0].append((frame, euler[0]))
                    baked[1].append((frame, euler[1]))
                    baked[2].append((frame, euler[2]))
                    baked[4].append((frame, loc[0]))
                    baked[5].append((frame, loc[1]))
                    baked[6].append((frame, loc[2]))
                    baked[7].append((frame, scale[0]))
                    baked[8].append((frame, scale[1]))
                    baked[9].append((frame, scale[2]))
            bpy.context.view_layer.update()

    reset_pose(armature)
    armature.animation_data.action = saved_action

    for idx in bake_indices:
        final_curves = _create_final_fcurves(name_of[idx], action)
        accum = bake_skeleton.bones[idx].accumulated_scale
        tol_scale = max(min(abs(c) for c in accum), _MIN_ACCUM_FOR_TOL)
        _write_baked_values(final_curves, baked_by_bone[idx], tol_scale)

    for raw in raw_by_bone.values():
        for curve in raw:
            if curve is not None:
                action.fcurves.remove(curve)


def _insert_raw_keyframes(track, action):
    """Create temp fcurves on the 'r'/'l'/'s' data paths and seed them with
    the decoded IR keyframes.

    In: track (BRBoneTrack); action (bpy.types.Action, fcurves mutated).
    Out: list[bpy.types.FCurve|None] of length _CHANNEL_COUNT; None for any
         channel that had no keyframes in the input (filled by
         _fill_missing_channels_with_rest next).
    """
    raw = [None] * _CHANNEL_COUNT
    for keyframe_channels, letter, indices in (
        (track.rotation, 'r', _ROT_INDICES),
        (track.location, 'l', _LOC_INDICES),
        (track.scale, 's', _SCL_INDICES),
    ):
        for component, idx in enumerate(indices):
            keyframes = keyframe_channels[component]
            if not keyframes:
                continue
            data_path = 'pose.bones["%s"].%s' % (track.bone_name, letter)
            curve = action.fcurves.new(data_path, index=component)
            for kf in keyframes:
                point = curve.keyframe_points.insert(kf.frame, kf.value)
                point.interpolation = kf.interpolation.value
            offset = len(curve.keyframe_points) - len(keyframes)
            for i, kf in enumerate(keyframes):
                point = curve.keyframe_points[offset + i]
                # FREE handle type is required: AUTO/AUTO_CLAMPED handles are
                # recomputed by Blender and would discard the tangents we
                # encoded from the HSD stream.
                if kf.handle_left is not None:
                    point.handle_left_type = 'FREE'
                    point.handle_left[:] = kf.handle_left
                if kf.handle_right is not None:
                    point.handle_right_type = 'FREE'
                    point.handle_right[:] = kf.handle_right
            curve.update()
            raw[idx] = curve
    return raw


def _fill_missing_channels_with_rest(track, action, raw_curves):
    """Seed any channel without keyframes with a single rest-pose value so
    evaluate() returns a sensible constant during the bake loop.

    In: track (BRBoneTrack); action (bpy.types.Action, mutated);
        raw_curves (list[bpy.types.FCurve|None], mutated — None slots filled).
    Out: None.
    """
    rest_per_letter = {
        'r': track.rest_rotation,
        'l': track.rest_position,
        's': track.rest_scale,
    }
    for letter, indices in (('r', _ROT_INDICES), ('l', _LOC_INDICES), ('s', _SCL_INDICES)):
        for component, idx in enumerate(indices):
            if raw_curves[idx] is not None:
                continue
            data_path = 'pose.bones["%s"].%s' % (track.bone_name, letter)
            curve = action.fcurves.new(data_path, index=component)
            curve.keyframe_points.insert(0, rest_per_letter[letter][component])
            raw_curves[idx] = curve


def _create_final_fcurves(bone_name, action):
    """Create the nine final fcurves (rotation_euler × 3, location × 3, scale × 3).

    In: bone_name (str); action (bpy.types.Action, fcurves mutated).
    Out: list[bpy.types.FCurve|None] of length _CHANNEL_COUNT; index 3 is
         always None (channel layout reserves it).
    """
    curves = [None] * _CHANNEL_COUNT
    for component in range(3):
        curves[component] = action.fcurves.new(
            'pose.bones["%s"].rotation_euler' % bone_name, index=component)
        curves[component + 4] = action.fcurves.new(
            'pose.bones["%s"].location' % bone_name, index=component)
        curves[component + 7] = action.fcurves.new(
            'pose.bones["%s"].scale' % bone_name, index=component)
    return curves


# Per-channel decimation tolerance. The bake produces a dense keyframe on
# every frame; most are redundant (a channel that barely moves, or moves
# near-linearly). Collapsing those to a sparse set within a visually
# imperceptible tolerance cuts fcurve-evaluation cost during playback by ~an
# order of magnitude without changing the pose the user sees (and the exporter
# re-samples the curve densely anyway). Rotation is in radians, so ~6e-4 rad ≈
# 0.03°; location/scale are in the model's units.
_DECIMATE_TOL = {0: 6e-4, 1: 6e-4, 2: 6e-4,
                 4: 1e-3, 5: 1e-3, 6: 1e-3,
                 7: 1e-3, 8: 1e-3, 9: 1e-3}
# Never scale the decimation tolerance below this — a genuinely tiny (hidden)
# accumulated scale would otherwise force a near-zero tolerance (no reduction);
# those bones are collapsed/invisible so a small residual error doesn't show.
_MIN_ACCUM_FOR_TOL = 0.05


def _write_baked_values(curves, baked, tol_scale=1.0):
    """Decimate each dense per-frame channel, then bulk-write it with BEZIER
    interpolation. Using add() once + per-slot assignment is O(n); per-frame
    insert() is O(n log k).

    ``tol_scale`` tightens the decimation tolerance for bones bound with a small
    accumulated scale: the skin deform amplifies a pose error by ``1/rest_scale``
    (a vertex bound to a 0.04-scale bone moves ~24× the bone's pose error), so
    the per-channel tolerance is scaled down by that rest scale to keep the
    *mesh* deviation within budget. Uniform bones (scale ≈ 1) decimate freely.

    In: curves (list[FCurve|None]); baked (list[list[tuple[int, float]]]);
        tol_scale (float, per-bone tolerance multiplier).
    Out: None; fcurves are mutated in place.
    """
    for idx in (0, 1, 2, 4, 5, 6, 7, 8, 9):
        curve = curves[idx]
        values = _decimate_keyframes(baked[idx], _DECIMATE_TOL[idx] * tol_scale)
        if not values:
            continue
        curve.keyframe_points.add(len(values))
        for i, (frame, value) in enumerate(values):
            point = curve.keyframe_points[i]
            point.co = (frame, value)
            # LINEAR (not BEZIER): the RDP decimation bounds the piecewise-linear
            # reconstruction error to the tolerance. BEZIER through the sparse
            # kept points would overshoot between them (unbounded), which on a
            # large-magnitude basis channel throws the pose off. Linear also
            # evaluates cheaper.
            point.interpolation = 'LINEAR'


def _decimate_keyframes(points, tol):
    """Ramer–Douglas–Peucker reduction of a dense (frame, value) sequence.

    Frames are monotonic, so deviation is measured vertically (value error)
    against the straight line between kept neighbours: a keyframe is kept only
    if dropping it would move the interpolated value by more than ``tol``.
    Endpoints are always kept.

    In: points (list[tuple[int, float]]); tol (float).
    Out: list[tuple[int, float]] — the retained keyframes, in order.
    """
    n = len(points)
    if n <= 2:
        return points
    keep = [False] * n
    keep[0] = keep[n - 1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        x0, y0 = points[a]
        x1, y1 = points[b]
        span = (x1 - x0) or 1.0
        worst_dev = tol
        worst_i = -1
        for i in range(a + 1, b):
            x, y = points[i]
            interpolated = y0 + (y1 - y0) * (x - x0) / span
            dev = abs(y - interpolated)
            if dev > worst_dev:
                worst_dev = dev
                worst_i = i
        if worst_i != -1:
            keep[worst_i] = True
            stack.append((a, worst_i))
            stack.append((worst_i, b))
    return [points[i] for i in range(n) if keep[i]]


def _build_material_tracks(br_action, action, material_lookup, mat_slot_indices,
                           max_frame, apply_color_tracks, apply_texture_uv_tracks,
                           logger):
    """Attach paired material animation tracks to the action as additional
    slots. Still consumes IR-shaped material tracks (carried through BR
    as pass-through until the materials stage migrates them).

    In: br_action (BRAction); action (bpy.types.Action, mutated);
        material_lookup (dict[str, bpy.types.Material]|None);
        mat_slot_indices (dict[bpy.types.Material, int], mutated);
        max_frame (int); apply_color_tracks / apply_texture_uv_tracks (callables
        injected from material_animations to avoid a circular import);
        logger (Logger).
    Out: int, number of material fcurves created across all material tracks.
    """
    if not br_action.material_tracks or not material_lookup:
        return 0

    if action.layers:
        layer = action.layers[0]
        strip = layer.strips[0]
    else:
        layer = action.layers.new("Layer")
        strip = layer.strips.new(type='KEYFRAME')

    animated_materials = set()
    mat_fcurve_count = 0
    for mat_track in br_action.material_tracks:
        mat = material_lookup.get(mat_track.material_mesh_name)
        logger.debug("    MatTrack lookup: '%s' → %s",
                     mat_track.material_mesh_name, mat.name if mat else 'NOT FOUND')
        if not mat:
            continue
        if id(mat) in animated_materials:
            logger.debug("    MatTrack '%s': skipping (material '%s' already animated)",
                         mat_track.material_mesh_name, mat.name)
            continue
        animated_materials.add(id(mat))

        mat_slot = action.slots.new('MATERIAL', mat.name or 'Material')
        channelbag = strip.channelbag(mat_slot, ensure=True)

        if not mat.animation_data:
            mat.animation_data_create()
        mat.animation_data.action = action
        mat.animation_data.action_slot = mat_slot

        before = len(channelbag.fcurves)
        apply_color_tracks(mat_track, mat, channelbag.fcurves, max_frame, logger)
        apply_texture_uv_tracks(mat_track, mat, channelbag.fcurves, logger)
        mat_fcurve_count += len(channelbag.fcurves) - before

        if mat not in mat_slot_indices:
            mat_slot_indices[mat] = len(action.slots) - 1

    return mat_fcurve_count


# ---------------------------------------------------------------------------
# Spline-path bones — unchanged from before. Still reads from the track's
# spline_path pass-through until a dedicated stage migrates it.
# ---------------------------------------------------------------------------

_SPLINE_TYPE_MAP = {
    0: 'POLY',
    2: 'NURBS',
}


def _apply_path_constraint(track, action, armature, logger):
    """Create a Blender curve from spline points and add a FOLLOW_PATH
    constraint. Bone follows the curve; path parameter is animated via
    the constraint's offset fcurve.

    In: track (BRBoneTrack with non-None spline_path); action (bpy.types.Action,
        gets an offset fcurve); armature (bpy.types.Object);
        logger (Logger).
    Out: None. Creates a bpy.types.Curve object parented to the armature and
         adds FOLLOW_PATH + LIMIT_LOCATION constraints on the pose bone.
    """
    bone_name = track.bone_name
    path = track.spline_path
    points = path.control_points
    spline_type = path.curve_type
    num_cvs = path.num_control_points
    tension = path.tension

    curve_data = bpy.data.curves.new('path_' + bone_name, 'CURVE')
    curve_data.use_path = True
    curve_data.dimensions = '3D'
    curve_obj = bpy.data.objects.new('Path_' + bone_name, curve_data)
    curve_obj.parent = armature
    if path.world_matrix:
        curve_obj.matrix_local = Matrix(path.world_matrix)
    bpy.context.scene.collection.objects.link(curve_obj)
    bpy.context.view_layer.update()

    if spline_type == 0:
        spline = curve_data.splines.new('POLY')
        spline.points.add(len(points) - 1)
        for i, pt in enumerate(points):
            spline.points[i].co = (pt[0], pt[1], pt[2], 1.0)

    elif spline_type == 1:
        spline = curve_data.splines.new('BEZIER')
        spline.bezier_points.add(num_cvs - 1)
        for i in range(num_cvs):
            spline.bezier_points[i].co = points[3 * i]
            if i > 0:
                spline.bezier_points[i].handle_left = points[3 * (i - 1) + 2]
            if i < num_cvs - 1:
                spline.bezier_points[i].handle_right = points[3 * i + 1]

    elif spline_type == 2:
        spline = curve_data.splines.new('NURBS')
        spline.points.add(len(points) - 1)
        spline.order_u = 4
        for i, pt in enumerate(points):
            spline.points[i].co = (pt[0], pt[1], pt[2], 1.0)

    elif spline_type == 3:
        spline = curve_data.splines.new('BEZIER')
        spline.bezier_points.add(num_cvs - 1)
        for i in range(num_cvs):
            cp = points[i + 1]
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

    pose_bone = armature.pose.bones[bone_name]

    path_constr = pose_bone.constraints.new('FOLLOW_PATH')
    pose_bone.constraints.move(len(pose_bone.constraints) - 1, 0)
    path_constr.target = curve_obj

    limit_constr = pose_bone.constraints.new('LIMIT_LOCATION')
    pose_bone.constraints.move(len(pose_bone.constraints) - 1, 0)
    for axis in ('x', 'y', 'z'):
        setattr(limit_constr, 'use_min_' + axis, True)
        setattr(limit_constr, 'use_max_' + axis, True)
        setattr(limit_constr, 'min_' + axis, 0.0)
        setattr(limit_constr, 'max_' + axis, 0.0)

    path_duration = curve_data.path_duration
    data_path = 'pose.bones["%s"].constraints["%s"].offset' % (bone_name, path_constr.name)
    offset_curve = action.fcurves.new(data_path)
    for kf in path.parameter_keyframes:
        scaled_value = kf.value * -path_duration
        point = offset_curve.keyframe_points.insert(kf.frame, scaled_value)
        point.interpolation = kf.interpolation.value
    kf_offset = len(offset_curve.keyframe_points) - len(path.parameter_keyframes)
    for i, kf in enumerate(path.parameter_keyframes):
        point = offset_curve.keyframe_points[kf_offset + i]
        if kf.handle_left:
            point.handle_left = (kf.handle_left[0], kf.handle_left[1] * -path_duration)
        if kf.handle_right:
            point.handle_right = (kf.handle_right[0], kf.handle_right[1] * -path_duration)

    logger.info("  PATH_SETUP bone=%s curve_obj=%s path_duration=%d",
                bone_name, curve_obj.name, path_duration)
