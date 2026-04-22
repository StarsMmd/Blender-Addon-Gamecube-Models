"""Unit tests for the Plan phase's IR animations → BR actions helper and the
pure compute_pose_basis formula.

compute_pose_basis was previously entangled with bpy inside _bake_bone_track;
lifting it out means the per-frame pose-basis math can be directly tested
with synthetic inputs, no Blender runtime required.
"""
import math

from shared.IR.skeleton import IRBone, IRModel
from shared.IR.enums import ScaleInheritance, Interpolation
from shared.IR.animation import (
    IRBoneAnimationSet, IRBoneTrack, IRKeyframe,
)
from shared.BR.actions import BRAction, BRBoneTrack, BRBakeContext, BRMaterialTrack
from shared.helpers.math_shim import (
    Matrix, Vector, compile_srt_matrix, matrix_to_list,
)
from importer.phases.plan.helpers.animations import (
    plan_actions,
    choose_bake_strategy,
    compute_pose_basis,
    attach_parent_edit_scale_corrections,
)


IDENTITY = matrix_to_list(Matrix.Identity(4))


def _kf(frame, value):
    return IRKeyframe(frame=frame, value=value, interpolation=Interpolation.LINEAR)


def _make_bone(name, parent_index=None, scale=(1.0, 1.0, 1.0), accumulated=None,
               scale_correction=None):
    return IRBone(
        name=name,
        parent_index=parent_index,
        position=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
        scale=scale,
        inverse_bind_matrix=None,
        flags=0,
        is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED,
        ik_shrink=False,
        world_matrix=IDENTITY,
        local_matrix=IDENTITY,
        normalized_world_matrix=IDENTITY,
        normalized_local_matrix=IDENTITY,
        scale_correction=scale_correction if scale_correction is not None else IDENTITY,
        accumulated_scale=accumulated if accumulated is not None else scale,
    )


def _make_ir_track(bone_index, bone_name="B", rest_scale=(1.0, 1.0, 1.0),
                   rest_rotation=(0, 0, 0), rest_position=(0, 0, 0),
                   rotation=None, location=None, scale=None,
                   end_frame=10, spline_path=None):
    rest_local = compile_srt_matrix(rest_scale, rest_rotation, rest_position)
    return IRBoneTrack(
        bone_name=bone_name,
        bone_index=bone_index,
        rotation=rotation or [[], [], []],
        location=location or [[], [], []],
        scale=scale or [[], [], []],
        rest_local_matrix=matrix_to_list(rest_local),
        rest_rotation=rest_rotation,
        rest_position=rest_position,
        rest_scale=rest_scale,
        end_frame=end_frame,
        spline_path=spline_path,
    )


class TestChooseBakeStrategy:

    def test_uniform_accumulated_scale_picks_aligned(self):
        assert choose_bake_strategy((1.0, 1.0, 1.0)) == 'aligned'

    def test_non_uniform_picks_direct(self):
        assert choose_bake_strategy((1.221, 0.549, 1.0)) == 'direct'

    def test_all_zero_accumulated_picks_direct(self):
        assert choose_bake_strategy((0.0, 0.0, 0.0)) == 'direct'

    def test_slight_variation_within_ratio_picks_aligned(self):
        assert choose_bake_strategy((1.0, 1.05, 1.03)) == 'aligned'

    def test_negative_uniform_picks_aligned(self):
        assert choose_bake_strategy((-1.0, -1.0, -1.0)) == 'aligned'


class TestPlanActions:

    def test_empty_anim_sets_yield_empty_list(self):
        assert plan_actions([], []) == []

    def test_single_track_translates_to_br_action(self):
        bones = [_make_bone("Root")]
        ir_track = _make_ir_track(bone_index=0, bone_name="Root")
        anim_set = IRBoneAnimationSet(name="Idle", tracks=[ir_track])
        br_actions = plan_actions([anim_set], bones)

        assert len(br_actions) == 1
        action = br_actions[0]
        assert isinstance(action, BRAction)
        assert action.name == "Idle"
        assert len(action.bone_tracks) == 1

        track = action.bone_tracks[0]
        assert isinstance(track, BRBoneTrack)
        assert track.bone_name == "Root"
        assert track.bone_index == 0
        assert track.bake_context.strategy == 'aligned'

    def test_non_uniform_ancestor_selects_direct_strategy(self):
        bones = [_make_bone("Root", accumulated=(1.2, 0.5, 1.0))]
        ir_track = _make_ir_track(bone_index=0, bone_name="Root")
        anim_set = IRBoneAnimationSet(name="A", tracks=[ir_track])
        br_actions = plan_actions([anim_set], bones)
        assert br_actions[0].bone_tracks[0].bake_context.strategy == 'direct'

    def test_material_tracks_carried_through_as_br_material_track(self):
        from shared.IR.animation import IRMaterialTrack
        mat_track = IRMaterialTrack(
            material_mesh_name='mesh_0_Root',
            diffuse_r=[_kf(0, 0.5)],
            alpha=[_kf(0, 1.0)],
        )
        anim_set = IRBoneAnimationSet(name="A", tracks=[], material_tracks=[mat_track])
        br_actions = plan_actions([anim_set], [])
        assert len(br_actions[0].material_tracks) == 1
        assert isinstance(br_actions[0].material_tracks[0], BRMaterialTrack)
        assert br_actions[0].material_tracks[0].material_mesh_name == 'mesh_0_Root'

    def test_parent_edit_scale_correction_attached(self):
        """attach_parent_edit_scale_corrections fills the aligned-path link
        that can't be resolved from the track alone."""
        parent_sc = matrix_to_list(Matrix.Scale(2.0, 4))
        bones = [
            _make_bone("Root", scale_correction=parent_sc),
            _make_bone("Child", parent_index=0),
        ]
        ir_track = _make_ir_track(bone_index=1, bone_name="Child")
        anim_set = IRBoneAnimationSet(name="A", tracks=[ir_track])
        br_actions = plan_actions([anim_set], bones)
        assert br_actions[0].bone_tracks[0].bake_context.parent_edit_scale_correction is None
        attach_parent_edit_scale_corrections(br_actions, bones)
        assert br_actions[0].bone_tracks[0].bake_context.parent_edit_scale_correction == parent_sc


class TestComputePoseBasisDirectPath:
    """Direct-path formula: used when accumulated parent scale is non-uniform.
    Translation and rotation are decomposed against the rest; scale is the
    per-channel animated/rest ratio."""

    def _make_ctx(self, rest_scale=(1.0, 1.0, 1.0), rest_position=(0.0, 0.0, 0.0),
                  rest_rotation=(0.0, 0.0, 0.0), has_path=False):
        rest_base = compile_srt_matrix(rest_scale, rest_rotation, rest_position)
        trans, quat, scl = rest_base.decompose()
        return BRBakeContext(
            strategy='direct',
            rest_base=matrix_to_list(rest_base),
            rest_base_inv=matrix_to_list(rest_base.inverted_safe()),
            has_path=has_path,
            rest_translation=(trans.x, trans.y, trans.z),
            rest_rotation_quat=(quat.w, quat.x, quat.y, quat.z),
            rest_scale=(scl.x, scl.y, scl.z),
        )

    def test_rest_pose_yields_identity_basis(self):
        """Animated SRT == rest SRT → pose basis is identity."""
        ctx = self._make_ctx()
        loc, rot, scl = compute_pose_basis(ctx, (1.0, 1.0, 1.0), (0, 0, 0), (0, 0, 0))
        assert all(abs(v) < 1e-6 for v in loc)
        assert all(abs(v) < 1e-6 for v in rot)
        assert all(abs(v - 1.0) < 1e-6 for v in scl)

    def test_scale_is_per_channel_ratio_against_rest(self):
        """Direct path divides animated scale by rest scale."""
        ctx = self._make_ctx(rest_scale=(2.0, 4.0, 0.5))
        _, _, scl = compute_pose_basis(ctx, (1.0, 1.0, 1.0), (0, 0, 0), (0, 0, 0))
        assert abs(scl[0] - 0.5) < 1e-6
        assert abs(scl[1] - 0.25) < 1e-6
        assert abs(scl[2] - 2.0) < 1e-6

    def test_near_zero_rest_scale_falls_back_to_animated(self):
        """When rest component is near zero, the basis uses the animated
        value directly (avoiding division by ~0)."""
        ctx = self._make_ctx(rest_scale=(1e-9, 1.0, 1.0))
        _, _, scl = compute_pose_basis(ctx, (3.0, 1.0, 1.0), (0, 0, 0), (0, 0, 0))
        assert abs(scl[0] - 3.0) < 1e-6

    def test_translated_animated_loc_produces_rotated_delta(self):
        """When rest is at origin with no rotation, animated translation
        passes through as the basis location."""
        ctx = self._make_ctx()
        loc, _, _ = compute_pose_basis(ctx, (1.0, 1.0, 1.0), (0, 0, 0), (5.0, 0.0, 0.0))
        assert abs(loc[0] - 5.0) < 1e-5
        assert abs(loc[1]) < 1e-5
        assert abs(loc[2]) < 1e-5

    def test_basis_scale_clamped_at_max(self):
        """A pathological rest/animated combination shouldn't produce
        unbounded basis scale — the 100.0 clamp keeps runaway values sane."""
        ctx = self._make_ctx(rest_scale=(0.01, 1.0, 1.0))
        _, _, scl = compute_pose_basis(ctx, (100.0, 1.0, 1.0), (0, 0, 0), (0, 0, 0))
        # 100.0 / 0.01 = 10000, but clamp caps at 100.
        assert abs(scl[0] - 100.0) < 1e-5


class TestComputePoseBasisAlignedPath:
    """Aligned-path formula: legacy edit_scale_correction sandwich."""

    def _make_ctx(self):
        """Trivial aligned context: identity rest, identity edit corrections."""
        return BRBakeContext(
            strategy='aligned',
            rest_base=IDENTITY,
            rest_base_inv=IDENTITY,
            has_path=False,
            rest_translation=(0.0, 0.0, 0.0),
            rest_rotation_quat=(1.0, 0.0, 0.0, 0.0),
            rest_scale=(1.0, 1.0, 1.0),
            local_edit=IDENTITY,
            edit_scale_correction=IDENTITY,
            parent_edit_scale_correction=None,
        )

    def test_rest_pose_yields_identity_basis(self):
        ctx = self._make_ctx()
        loc, rot, scl = compute_pose_basis(ctx, (1.0, 1.0, 1.0), (0, 0, 0), (0, 0, 0))
        assert all(abs(v) < 1e-6 for v in loc)
        assert all(abs(v) < 1e-6 for v in rot)
        assert all(abs(v - 1.0) < 1e-6 for v in scl)

    def test_animated_translation_passes_through(self):
        ctx = self._make_ctx()
        loc, _, _ = compute_pose_basis(ctx, (1.0, 1.0, 1.0), (0, 0, 0), (3.0, 2.0, 1.0))
        assert abs(loc[0] - 3.0) < 1e-5
        assert abs(loc[1] - 2.0) < 1e-5
        assert abs(loc[2] - 1.0) < 1e-5

    def test_animated_scale_passes_through(self):
        """Identity corrections + identity rest → basis scale equals animated scale."""
        ctx = self._make_ctx()
        _, _, scl = compute_pose_basis(ctx, (2.5, 0.5, 1.5), (0, 0, 0), (0, 0, 0))
        assert abs(scl[0] - 2.5) < 1e-5
        assert abs(scl[1] - 0.5) < 1e-5
        assert abs(scl[2] - 1.5) < 1e-5
