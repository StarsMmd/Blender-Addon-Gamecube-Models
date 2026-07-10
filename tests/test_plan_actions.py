"""Unit tests for the Plan phase's IR animations → BR actions helper and the
pure-math NONE-inheritance pose bake.

The bake (``bake_frame``) reproduces the GX runtime pose under Blender's
``inherit_scale='NONE'`` without a Blender runtime: it composes each bone's GX
world per frame and inverts NONE's closed-form forward map to a shear-free
basis. These tests validate the round trip invert∘forward against independently
composed GX chains — including non-uniform, compound-rotated, multi-level
chains that the old aligned/direct hybrid could not represent. The forward map
itself is validated against real bpy end-to-end in the scale-inheritance probes
(not run here, no bpy).
"""
import math

from shared.IR.skeleton import IRBone
from shared.IR.enums import ScaleInheritance, Interpolation
from shared.IR.animation import IRBoneAnimationSet, IRBoneTrack, IRKeyframe
from shared.BR.actions import BRAction, BRBoneTrack, BRMaterialTrack, BRBakeSkeleton
from shared.helpers.math_shim import Matrix, compile_srt_matrix, matrix_to_list
from importer.phases.plan.helpers.animations import (
    plan_actions,
    build_bake_skeleton,
    bake_frame,
    compute_bake_plan,
    scale_baked_indices,
)


IDENTITY = matrix_to_list(Matrix.Identity(4))


def _kf(frame, value):
    return IRKeyframe(frame=frame, value=value, interpolation=Interpolation.LINEAR)


def _make_bone(name, parent_index=None, scale=(1.0, 1.0, 1.0),
               rotation=(0.0, 0.0, 0.0), position=(0.0, 0.0, 0.0),
               world_matrix=None, normalized_world_matrix=None, flags=0,
               accumulated=None):
    return IRBone(
        name=name,
        parent_index=parent_index,
        position=position,
        rotation=rotation,
        scale=scale,
        inverse_bind_matrix=None,
        flags=flags,
        is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED,  # don't-care for the NONE bake
        ik_shrink=False,
        world_matrix=world_matrix if world_matrix is not None else IDENTITY,
        local_matrix=IDENTITY,
        normalized_world_matrix=(normalized_world_matrix
                                 if normalized_world_matrix is not None else IDENTITY),
        normalized_local_matrix=IDENTITY,
        scale_correction=IDENTITY,
        accumulated_scale=accumulated if accumulated is not None else scale,
    )


def _make_ir_track(bone_index, bone_name="B", rest_scale=(1.0, 1.0, 1.0),
                   rest_rotation=(0, 0, 0), rest_position=(0, 0, 0),
                   rotation=None, location=None, scale=None, end_frame=10):
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
        spline_path=None,
    )


# ---------------------------------------------------------------------------
# GX reference chain (independent of the bake code under test).
# ---------------------------------------------------------------------------

def _gx_chain(joints):
    """Compose a GX bone chain. joints: list of dicts scale/rot/pos, each bone's
    parent is the previous. Returns (world_matrices, accumulated_scales)."""
    worlds, accums = [], []
    pw, pa = None, None
    for j in joints:
        local = compile_srt_matrix(j['scale'], j['rot'], j['pos'], pa)
        world = local if pw is None else pw @ local
        accum = tuple(j['scale']) if pa is None else tuple(j['scale'][c] * pa[c] for c in range(3))
        worlds.append(world)
        accums.append(accum)
        pw, pa = world, accum
    return worlds, accums


def _normalized(m):
    nw = m.to_3x3().normalized().to_4x4()
    t = m.translation
    rows = [[nw[i][j] for j in range(4)] for i in range(4)]
    rows[0][3], rows[1][3], rows[2][3] = t[0], t[1], t[2]
    return Matrix(rows)


def _skeleton_from_chain(rest_joints):
    """Build a linear-chain BRBakeSkeleton whose edit-bone rests come from the
    GX rest worlds of ``rest_joints``."""
    rest_w, rest_accums = _gx_chain(rest_joints)
    bones = []
    for i, j in enumerate(rest_joints):
        bone = _make_bone(
            f"b{i}", parent_index=(i - 1 if i > 0 else None),
            scale=j['scale'], rotation=j['rot'], position=j['pos'],
            world_matrix=matrix_to_list(rest_w[i]),
            normalized_world_matrix=matrix_to_list(_normalized(rest_w[i])),
            accumulated=rest_accums[i],
        )
        bones.append(bone)
    return build_bake_skeleton(bones), rest_w


class TestPlanActions:

    def test_empty_anim_sets_yield_empty_list(self):
        assert plan_actions([], []) == []

    def test_single_track_translates_to_br_action(self):
        ir_track = _make_ir_track(bone_index=0, bone_name="Root")
        anim_set = IRBoneAnimationSet(name="Idle", tracks=[ir_track])
        br_actions = plan_actions([anim_set], [_make_bone("Root")])

        assert len(br_actions) == 1
        action = br_actions[0]
        assert isinstance(action, BRAction)
        assert action.name == "Idle"
        track = action.bone_tracks[0]
        assert isinstance(track, BRBoneTrack)
        assert track.bone_name == "Root"
        assert track.bone_index == 0

    def test_material_tracks_carried_through(self):
        from shared.IR.animation import IRMaterialTrack
        mat_track = IRMaterialTrack(
            material_mesh_name='mesh_0_Root',
            diffuse_r=[_kf(0, 0.5)],
            alpha=[_kf(0, 1.0)],
        )
        anim_set = IRBoneAnimationSet(name="A", tracks=[], material_tracks=[mat_track])
        br_actions = plan_actions([anim_set], [])
        assert isinstance(br_actions[0].material_tracks[0], BRMaterialTrack)
        assert br_actions[0].material_tracks[0].material_mesh_name == 'mesh_0_Root'


class TestBuildBakeSkeleton:

    def test_parent_first_order(self):
        # Bones listed child-before-parent; dfs_order must fix that.
        bones = [
            _make_bone("child", parent_index=1),
            _make_bone("root", parent_index=None),
        ]
        skel = build_bake_skeleton(bones)
        assert isinstance(skel, BRBakeSkeleton)
        assert skel.dfs_order.index(1) < skel.dfs_order.index(0)

    def test_classical_scaling_flag_extracted(self):
        from shared.Constants.hsd import JOBJ_CLASSICAL_SCALING
        bones = [
            _make_bone("plain", flags=0),
            _make_bone("classical", flags=JOBJ_CLASSICAL_SCALING),
        ]
        skel = build_bake_skeleton(bones)
        assert skel.bones[0].classical_scaling is False
        assert skel.bones[1].classical_scaling is True


class TestScaleBakedIndices:
    """Bake-default partition: a bone reads back under NONE if its rest scale is
    non-uniform, its scale is animated, or any ancestor's is (the closure). The
    rest read back under native ALIGNED. Precomputed on the skeleton."""

    def test_fully_uniform_no_scale_anim_is_empty(self):
        rest = [dict(scale=(1, 1, 1), rot=(0, 0, 0), pos=(0, 0, 0)),
                dict(scale=(2, 2, 2), rot=(0, 0, 0), pos=(0, 1, 0)),   # uniform non-identity
                dict(scale=(1, 1, 1), rot=(0, 0, 0), pos=(0, 1, 0))]
        skel, _ = _skeleton_from_chain(rest)
        assert scale_baked_indices(skel) == set()

    def test_nonuniform_rest_and_descendants_baked(self):
        rest = [dict(scale=(1, 1, 1), rot=(0, 0, 0), pos=(0, 0, 0)),
                dict(scale=(2, 1, 0.5), rot=(0, 0, 0), pos=(0, 1, 0)),  # non-uniform
                dict(scale=(1, 1, 1), rot=(0, 0, 0), pos=(0, 1, 0))]    # inherits non-uniform accum
        skel, _ = _skeleton_from_chain(rest)
        assert scale_baked_indices(skel) == {1, 2}

    def test_scale_animated_bone_and_descendants_baked(self):
        """A bone with uniform rest scale but any scale animation reads back
        under NONE, and so do its descendants (they'd inherit its scale)."""
        bones = [
            _make_bone("b0", accumulated=(1, 1, 1)),
            _make_bone("b1", parent_index=0, accumulated=(1, 1, 1)),
            _make_bone("b2", parent_index=1, accumulated=(1, 1, 1)),
        ]
        track = _make_ir_track(1, "b1", scale=[[_kf(0, 1.0), _kf(5, 2.0)], [], []])
        anim = IRBoneAnimationSet(name="A", tracks=[track])
        skel = build_bake_skeleton(bones, [anim])
        assert scale_baked_indices(skel) == {1, 2}

    def test_rotation_only_animation_stays_aligned(self):
        """Rotation/location animation alone does not force NONE."""
        bones = [_make_bone("b0", accumulated=(1, 1, 1))]
        track = _make_ir_track(0, "b0", rotation=[[_kf(0, 0.0), _kf(5, 1.0)], [], []])
        anim = IRBoneAnimationSet(name="A", tracks=[track])
        skel = build_bake_skeleton(bones, [anim])
        assert scale_baked_indices(skel) == set()


class TestComputeBakePlan:

    def test_animated_and_nonuniform_bones_are_baked(self):
        rest = [dict(scale=(1, 1, 1), rot=(0, 0, 0), pos=(0, 0, 0)),       # uniform root
                dict(scale=(2, 1, 0.5), rot=(0, 0, 0), pos=(0, 1, 0)),     # non-uniform
                dict(scale=(1, 1, 1), rot=(0, 0, 0), pos=(0, 1, 0))]       # uniform child (inherits nonuniform accum)
        skel, _ = _skeleton_from_chain(rest)
        bake_indices, levels = compute_bake_plan(skel, animated_indices=set())
        # bone 1 is non-uniform; bone 2 inherits a non-uniform accumulated scale.
        assert 1 in bake_indices and 2 in bake_indices
        # A purely-uniform root with no animation need not be baked.
        assert 0 not in bake_indices
        # Depth levels are parent-before-child.
        d1 = next(d for d, lvl in enumerate(levels) if 1 in lvl)
        d2 = next(d for d, lvl in enumerate(levels) if 2 in lvl)
        assert d1 < d2

    def test_animated_uniform_bone_is_baked(self):
        rest = [dict(scale=(1, 1, 1), rot=(0, 0, 0), pos=(0, 0, 0))]
        skel, _ = _skeleton_from_chain(rest)
        bake_indices, _ = compute_bake_plan(skel, animated_indices={0})
        assert bake_indices == [0]


class TestBakeFrame:
    """The core: bake_frame emits the GX target pose per bone. Build applies it
    via pose_bone.matrix so Blender inverts NONE (verified end-to-end under bpy
    in the scale-inheritance probes / deoxys validation, not here)."""

    def test_rest_frame_targets_equal_normalized_rest(self):
        """At rest, the target pose is the normalized edit-bone rest (identity
        pose delta)."""
        rest = [dict(scale=(2, 1, 0.5), rot=(0, 0, 0), pos=(0, 0, 0)),
                dict(scale=(1, 1, 1), rot=(0.2, 0.1, 0.0), pos=(0.3, 1, 0.2))]
        skel, _ = _skeleton_from_chain(rest)
        frame_srts = {i: (rest[i]['scale'], rest[i]['rot'], rest[i]['pos'])
                      for i in range(len(rest))}
        bake_indices, _ = compute_bake_plan(skel, set(frame_srts))
        targets = bake_frame(skel, frame_srts, bake_indices)
        for i in bake_indices:
            norm_rest = Matrix(skel.bones[i].normalized_rest_matrix)
            got = Matrix(targets[i])
            err = max(abs(got[r][c] - norm_rest[r][c]) for r in range(3) for c in range(4))
            assert err < 1e-6

    def test_targets_reproduce_gx_nonuniform_compound_chain(self):
        rest = [dict(scale=(2, 1, 0.5), rot=(0, 0, 0), pos=(0, 0, 0)),
                dict(scale=(1.3, 0.6, 1.4), rot=(math.radians(10), 0, math.radians(5)), pos=(0.3, 1, 0.2)),
                dict(scale=(1, 1, 1), rot=(0, math.radians(20), 0), pos=(0.1, 1, 0)),
                dict(scale=(1, 1, 1), rot=(0, 0, 0), pos=(0, 1, 0))]
        anim = [dict(scale=(2.5, 1.2, 0.4), rot=(0, 0, math.radians(15)), pos=(0, 0, 0)),
                dict(scale=(0.9, 1.5, 1.1), rot=(math.radians(30), math.radians(25), math.radians(15)), pos=(0.3, 1, 0.2)),
                dict(scale=(1, 1, 1), rot=(math.radians(20), math.radians(-15), math.radians(10)), pos=(0.1, 1, 0)),
                dict(scale=(1.4, 0.7, 1.0), rot=(math.radians(-12), math.radians(8), math.radians(22)), pos=(0, 1, 0))]
        skel, rest_w = _skeleton_from_chain(rest)
        anim_w, _ = _gx_chain(anim)
        animated = set(range(len(anim)))
        frame_srts = {i: (anim[i]['scale'], anim[i]['rot'], anim[i]['pos']) for i in animated}
        bake_indices, _ = compute_bake_plan(skel, animated)
        targets = bake_frame(skel, frame_srts, bake_indices)
        for i in animated:
            norm_rest = Matrix(skel.bones[i].normalized_rest_matrix)
            expected = anim_w[i] @ rest_w[i].inverted_safe() @ norm_rest
            got = Matrix(targets[i])
            err = max(abs(got[r][c] - expected[r][c]) for r in range(3) for c in range(4))
            assert err < 1e-5, f"bone {i} target err {err}"

    def test_unanimated_bone_follows_animated_ancestor(self):
        """An un-animated non-uniform bone still gets a target that tracks its
        animated parent (not the static rest world)."""
        rest = [dict(scale=(2, 1, 0.5), rot=(0, 0, 0), pos=(0, 0, 0)),
                dict(scale=(1, 1, 1), rot=(0, 0, 0), pos=(0.3, 1, 0.2))]
        anim = [dict(scale=(2, 1, 0.5), rot=(0, 0, math.radians(40)), pos=(0, 0, 0)),
                dict(scale=(1, 1, 1), rot=(0, 0, 0), pos=(0.3, 1, 0.2))]
        skel, rest_w = _skeleton_from_chain(rest)
        anim_w, _ = _gx_chain(anim)
        frame_srts = {0: (anim[0]['scale'], anim[0]['rot'], anim[0]['pos'])}  # only bone 0 animated
        bake_indices, _ = compute_bake_plan(skel, {0})
        assert 1 in bake_indices  # non-uniform-accum → baked even though un-animated
        targets = bake_frame(skel, frame_srts, bake_indices)
        norm_rest = Matrix(skel.bones[1].normalized_rest_matrix)
        expected = anim_w[1] @ rest_w[1].inverted_safe() @ norm_rest
        got = Matrix(targets[1])
        err = max(abs(got[r][c] - expected[r][c]) for r in range(3) for c in range(4))
        assert err < 1e-5
