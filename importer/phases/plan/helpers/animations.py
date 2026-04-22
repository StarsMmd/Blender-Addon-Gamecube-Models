"""IR animation sets → BR actions conversion + pure pose-basis formula.

Two responsibilities:

1. ``plan_actions``: convert a list of IRBoneAnimationSet into a list of
   BRAction, pre-computing per-bone-track bake context (rest matrices, SRT
   decomposition, strategy selection) so the per-frame computation at
   build time is reduced to a pure math call.

2. ``compute_pose_basis``: the per-frame pose-basis formula, lifted out of
   the old ``_bake_bone_track``. Takes a BRBakeContext + animated SRT
   tuple and returns ``(loc, rot_euler, scale)`` as plain tuples. Pure
   Python + math_shim — no bpy, no mathutils in sight — so the formula is
   directly unit-testable.
"""
import math

try:
    from .....shared.BR.actions import (
        BRAction, BRBoneTrack, BRBakeContext, BRMaterialTrack,
    )
    from .....shared.helpers.math_shim import (
        Matrix, Vector, Euler, compile_srt_matrix, matrix_to_list,
    )
except (ImportError, SystemError):
    from shared.BR.actions import (
        BRAction, BRBoneTrack, BRBakeContext, BRMaterialTrack,
    )
    from shared.helpers.math_shim import (
        Matrix, Vector, Euler, compile_srt_matrix, matrix_to_list,
    )


_UNIFORM_RATIO = 1.1
_NEAR_ZERO_SCALE = 1e-6
_MAX_BASIS_SCALE = 100.0
_PATH_ROTATION_X = -math.pi / 2  # GC Y-up → Blender Z-up rotation for spline-followers


def plan_actions(ir_anim_sets, ir_bones):
    """Convert a list of IRBoneAnimationSet into BRAction list."""
    actions = []
    for anim_set in ir_anim_sets:
        actions.append(_plan_single_action(anim_set, ir_bones))
    return actions


def _plan_single_action(anim_set, ir_bones):
    bone_tracks = [
        _plan_bone_track(track, ir_bones)
        for track in anim_set.tracks
    ]
    material_tracks = [
        BRMaterialTrack(
            material_mesh_name=mt.material_mesh_name,
            diffuse_r=mt.diffuse_r,
            diffuse_g=mt.diffuse_g,
            diffuse_b=mt.diffuse_b,
            alpha=mt.alpha,
            texture_uv_tracks=list(mt.texture_uv_tracks),
            loop=mt.loop,
        )
        for mt in anim_set.material_tracks
    ]
    return BRAction(
        name=anim_set.name,
        bone_tracks=bone_tracks,
        material_tracks=material_tracks,
        loop=anim_set.loop,
        is_static=anim_set.is_static,
    )


def _plan_bone_track(ir_track, ir_bones):
    ir_bone = ir_bones[ir_track.bone_index]
    has_path = ir_track.spline_path is not None
    strategy = choose_bake_strategy(ir_bone.accumulated_scale)
    context = build_bake_context(ir_track, ir_bone, strategy, has_path)
    return BRBoneTrack(
        bone_name=ir_track.bone_name,
        bone_index=ir_track.bone_index,
        rotation=ir_track.rotation,
        location=ir_track.location,
        scale=ir_track.scale,
        rest_rotation=ir_track.rest_rotation,
        rest_position=ir_track.rest_position,
        rest_scale=ir_track.rest_scale,
        end_frame=ir_track.end_frame,
        bake_context=context,
        spline_path=ir_track.spline_path,
    )


def choose_bake_strategy(accumulated_scale):
    """Pick 'aligned' (uniform parent scale) vs 'direct' (non-uniform).

    Mirrors the heuristic that was previously inline in ``_bake_bone_track``.
    A zero-ish component in the accumulation forces 'direct' because the
    aligned sandwich requires a safely invertible rest.
    """
    nonzero = [abs(x) for x in accumulated_scale if abs(x) > _NEAR_ZERO_SCALE]
    if not nonzero:
        return 'direct'
    mn = min(nonzero)
    mx = max(abs(x) for x in accumulated_scale)
    is_uniform = mx / max(mn, 1e-9) < _UNIFORM_RATIO
    return 'aligned' if is_uniform else 'direct'


def build_bake_context(ir_track, ir_bone, strategy, has_path):
    """Pre-compute the rest data consumed by ``compute_pose_basis``."""
    rest_base = Matrix(ir_track.rest_local_matrix)
    if has_path:
        rest_base = Matrix.Rotation(_PATH_ROTATION_X, 4, 'X') @ rest_base
    rest_base_inv = rest_base.inverted_safe()

    # SRT decomposition (used by 'direct' path + aligned's fallback).
    trans, quat, scl = rest_base.decompose()
    rest_translation = (trans.x, trans.y, trans.z)
    rest_rotation_quat = (quat.w, quat.x, quat.y, quat.z)
    rest_scale_tuple = (scl.x, scl.y, scl.z)

    local_edit = None
    edit_scale_correction = None
    parent_edit_sc = None
    if strategy == 'aligned':
        # The Plan phase stores these as plain 4x4 lists for portability;
        # compute_pose_basis wraps them in Matrix() again at use time.
        local_edit = list(ir_bone.normalized_local_matrix)
        edit_scale_correction = list(ir_bone.scale_correction)
        # Parent edit_scale_correction resolved later via the bone tree —
        # but IRBone doesn't carry a back-reference, so we resolve it here.
        parent_edit_sc = None  # set by the outer wiring below

    return BRBakeContext(
        strategy=strategy,
        rest_base=matrix_to_list(rest_base),
        rest_base_inv=matrix_to_list(rest_base_inv),
        has_path=has_path,
        rest_translation=rest_translation,
        rest_rotation_quat=rest_rotation_quat,
        rest_scale=rest_scale_tuple,
        local_edit=local_edit,
        edit_scale_correction=edit_scale_correction,
        parent_edit_scale_correction=parent_edit_sc,
    )


def attach_parent_edit_scale_corrections(br_actions, ir_bones):
    """Fill in ``parent_edit_scale_correction`` on every aligned track.

    Must run after ``plan_actions`` because the parent's scale_correction
    comes from IRBone, not from the track itself. Kept as a separate pass
    so ``_plan_bone_track`` can stay self-contained.
    """
    for action in br_actions:
        for track in action.bone_tracks:
            ctx = track.bake_context
            if ctx.strategy != 'aligned':
                continue
            parent_index = ir_bones[track.bone_index].parent_index
            if parent_index is None:
                ctx.parent_edit_scale_correction = None
            else:
                ctx.parent_edit_scale_correction = list(
                    ir_bones[parent_index].scale_correction
                )


# ---------------------------------------------------------------------------
# Per-frame pose-basis formula — pure math, no bpy.
# ---------------------------------------------------------------------------


def compute_pose_basis(ctx, animated_scale, animated_rotation, animated_location):
    """Given a BRBakeContext + animated SRT at some frame, return the pose
    basis as (location_tuple, euler_tuple, scale_tuple).

    The only decision this function makes is picking between the aligned
    formula (edit_scale_correction sandwich) and the direct SRT delta.
    """
    mtx = compile_srt_matrix(animated_scale, animated_rotation, animated_location)
    if ctx.has_path:
        mtx = Matrix.Rotation(_PATH_ROTATION_X, 4, 'X') @ mtx

    if ctx.strategy == 'aligned':
        trans_vec, rot_quat, scale_vec = _compute_aligned_basis(ctx, mtx)
        euler = rot_quat.to_euler()
    else:
        trans_vec, rot_quat, scale_vec = _compute_direct_basis(
            ctx, mtx, animated_rotation, animated_scale,
        )
        euler = rot_quat.to_euler('XYZ')

    scale_vec = _clamp_scale(scale_vec, _MAX_BASIS_SCALE)
    return (
        (trans_vec.x, trans_vec.y, trans_vec.z),
        (euler.x, euler.y, euler.z),
        (scale_vec.x, scale_vec.y, scale_vec.z),
    )


def _compute_aligned_basis(ctx, mtx):
    """Legacy ALIGNED sandwich: ``local_edit.inv @ parent_edit_sc @ mtx @ edit_sc.inv``.

    Falls back to direct ``rest_base_inv @ mtx`` if the sandwich's inversion
    fails (singular matrix), matching the pre-Plan behaviour.
    """
    try:
        local_edit = Matrix(ctx.local_edit)
        edit_sc = Matrix(ctx.edit_scale_correction)
        if ctx.parent_edit_scale_correction is not None:
            parent_edit_sc = Matrix(ctx.parent_edit_scale_correction)
            bmtx = local_edit.inverted() @ parent_edit_sc @ mtx @ edit_sc.inverted()
        else:
            bmtx = local_edit.inverted() @ mtx @ edit_sc.inverted()
    except ValueError:
        bmtx = Matrix(ctx.rest_base_inv) @ mtx
    return bmtx.decompose()


def _compute_direct_basis(ctx, mtx, animated_rotation, animated_scale):
    """Direct SRT delta against the rest pose.

    Used when the accumulated parent scale is non-uniform — avoids the
    shear contamination that decomposing an aligned-sandwich matrix
    produces under those conditions. Translation and rotation come from
    the composed matrix (so path rotation applies cleanly); scale is the
    raw animated component divided by the rest component (with a safe
    fallback for near-zero rests).
    """
    rest_loc = Vector(ctx.rest_translation)
    rest_quat_inv = _quaternion(ctx.rest_rotation_quat).inverted()
    rest_s = ctx.rest_scale

    anim_loc = Vector((mtx[0][3], mtx[1][3], mtx[2][3]))
    delta_pos = anim_loc - rest_loc
    trans_vec = delta_pos.copy()
    trans_vec.rotate(rest_quat_inv)

    anim_quat = Euler(animated_rotation, 'XYZ').to_quaternion()
    if ctx.has_path:
        path_quat = Matrix.Rotation(_PATH_ROTATION_X, 4, 'X').to_quaternion()
        anim_quat = path_quat @ anim_quat
    rot_quat = rest_quat_inv @ anim_quat

    scale_vec = Vector((
        _safe_scale_delta(rest_s[0], animated_scale[0]),
        _safe_scale_delta(rest_s[1], animated_scale[1]),
        _safe_scale_delta(rest_s[2], animated_scale[2]),
    ))
    return trans_vec, rot_quat, scale_vec


def _safe_scale_delta(rest_component, animated_component):
    if abs(rest_component) > _NEAR_ZERO_SCALE:
        return animated_component / rest_component
    return animated_component


def _quaternion(wxyz):
    """Lightweight wrapper so callers don't have to import Quaternion directly."""
    try:
        from mathutils import Quaternion
        return Quaternion(wxyz)
    except ImportError:
        from shared.helpers.math_shim import Quaternion  # math_shim re-export
        return Quaternion(wxyz)


def _clamp_scale(scale_vec, limit):
    return Vector((
        max(-limit, min(limit, scale_vec.x)),
        max(-limit, min(limit, scale_vec.y)),
        max(-limit, min(limit, scale_vec.z)),
    ))
