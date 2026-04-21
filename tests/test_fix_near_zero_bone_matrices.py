"""Model-wide visible-scale aggregation and near-zero rest rebind.

Covers compute_model_visible_scales() and fix_near_zero_bone_matrices():
  - Max-abs reduction across multiple animations.
  - Animations that keep the bone hidden throughout still get rebound rest.
  - Identity fallback when no animation reveals a visible value.
  - Descendant cascade through an intermediate tiny bone with no visible scale.
"""
from shared.IR.skeleton import IRBone
from shared.IR.enums import ScaleInheritance, Interpolation
from shared.IR.animation import IRBoneAnimationSet, IRBoneTrack, IRKeyframe
from shared.helpers.math_shim import Matrix, compile_srt_matrix, matrix_to_list
from importer.phases.describe.helpers.bones import (
    compute_model_visible_scales,
    fix_near_zero_bone_matrices,
)


def _kf(frame, value):
    return IRKeyframe(frame=frame, value=value, interpolation=Interpolation.LINEAR)


def _make_bone(name, parent_index, scale, position=(0.0, 0.0, 0.0), rotation=(0.0, 0.0, 0.0)):
    local = compile_srt_matrix(scale, rotation, position)
    if parent_index is None:
        world = local
    else:
        world = local  # caller recomputes via the helper below if needed
    return IRBone(
        name=name,
        parent_index=parent_index,
        position=position,
        rotation=rotation,
        scale=scale,
        inverse_bind_matrix=None,
        flags=0,
        is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED,
        ik_shrink=False,
        world_matrix=matrix_to_list(world),
        local_matrix=matrix_to_list(local),
        normalized_world_matrix=matrix_to_list(world.normalized()),
        normalized_local_matrix=matrix_to_list(local.normalized()),
        scale_correction=matrix_to_list(Matrix.Identity(4)),
        accumulated_scale=scale,
    )


def _recompute_world_cascade(bones):
    """Rebuild world_matrix entries from local + parent chain (DFS order)."""
    for i, bone in enumerate(bones):
        local = Matrix(bone.local_matrix)
        if bone.parent_index is None:
            world = local
        else:
            world = Matrix(bones[bone.parent_index].world_matrix) @ local
        bone.world_matrix = matrix_to_list(world)
        bone.normalized_world_matrix = matrix_to_list(world.normalized())


def _make_track(bone_index, bone_name, rest_scale, rest_rotation=(0, 0, 0),
                rest_position=(0, 0, 0), scale_keyframes=None):
    scale_channels = scale_keyframes or [[], [], []]
    rest_local = compile_srt_matrix(rest_scale, rest_rotation, rest_position)
    return IRBoneTrack(
        bone_name=bone_name,
        bone_index=bone_index,
        rotation=[[], [], []],
        location=[[], [], []],
        scale=scale_channels,
        rest_local_matrix=matrix_to_list(rest_local),
        rest_rotation=rest_rotation,
        rest_position=rest_position,
        rest_scale=rest_scale,
        end_frame=1.0,
    )


class TestComputeModelVisibleScales:

    def test_no_near_zero_bones_returns_empty(self):
        bones = [_make_bone("Root", None, (1.0, 1.0, 1.0))]
        result = compute_model_visible_scales(bones, [])
        assert result == {}

    def test_max_abs_across_multiple_animations(self):
        """Two animations on the same tiny bone: picks the max abs value per channel."""
        bones = [_make_bone("Hidden", None, (0.0, 0.0, 0.0))]
        anim_a = IRBoneAnimationSet(name="A", tracks=[
            _make_track(0, "Hidden", (0.0, 0.0, 0.0), scale_keyframes=[
                [_kf(0, 0.5), _kf(10, 0.5)],
                [_kf(0, 0.3), _kf(10, 0.3)],
                [_kf(0, 2.0), _kf(10, 2.0)],
            ]),
        ])
        anim_b = IRBoneAnimationSet(name="B", tracks=[
            _make_track(0, "Hidden", (0.0, 0.0, 0.0), scale_keyframes=[
                [_kf(0, 1.0), _kf(10, 1.0)],
                [_kf(0, 0.8), _kf(10, 0.8)],
                [_kf(0, 1.0), _kf(10, 1.0)],
            ]),
        ])
        result = compute_model_visible_scales(bones, [anim_a, anim_b])
        assert result[0] == (1.0, 0.8, 2.0)

    def test_hidden_only_animation_falls_back_to_identity(self):
        """If no animation reveals a visible scale, fall back to 1.0 per channel."""
        bones = [_make_bone("Hidden", None, (0.0, 0.0, 0.0))]
        anim = IRBoneAnimationSet(name="Hidden", tracks=[
            _make_track(0, "Hidden", (0.0, 0.0, 0.0), scale_keyframes=[
                [_kf(0, 0.0), _kf(10, 0.0)],
                [_kf(0, 0.0), _kf(10, 0.0)],
                [_kf(0, 0.0), _kf(10, 0.0)],
            ]),
        ])
        result = compute_model_visible_scales(bones, [anim])
        assert result[0] == (1.0, 1.0, 1.0)

    def test_no_animation_at_all_falls_back_to_identity(self):
        """Tiny bone with no track anywhere gets identity rest."""
        bones = [_make_bone("Lonely", None, (0.0, 0.0, 0.0))]
        result = compute_model_visible_scales(bones, [])
        assert result[0] == (1.0, 1.0, 1.0)

    def test_partial_channel_fallback(self):
        """Only some channels revealed; the rest fall back to 1.0."""
        bones = [_make_bone("Mixed", None, (0.0, 0.0, 0.0))]
        anim = IRBoneAnimationSet(name="A", tracks=[
            _make_track(0, "Mixed", (0.0, 0.0, 0.0), scale_keyframes=[
                [_kf(0, 2.5)],   # X revealed
                [],              # Y never appears
                [_kf(0, 0.0)],   # Z only ever tiny
            ]),
        ])
        result = compute_model_visible_scales(bones, [anim])
        assert result[0] == (2.5, 1.0, 1.0)

    def test_negative_rest_preserves_sign(self):
        """Negative tiny rest scale keeps its sign when falling back."""
        bones = [_make_bone("NegHidden", None, (-0.0001, 0.0, 0.0))]
        result = compute_model_visible_scales(bones, [])
        assert result[0] == (-1.0, 1.0, 1.0)


class TestFixNearZeroBoneMatrices:

    def test_rebound_rest_local_matrix_propagates_to_all_tracks(self):
        """Every track on a tiny bone gets its rest_local_matrix rewritten,
        including tracks whose own animation keeps the bone hidden."""
        bones = [_make_bone("Hidden", None, (0.0, 0.0, 0.0))]

        # Animation A reveals visible scale 2.0 in channel X.
        track_a = _make_track(0, "Hidden", (0.0, 0.0, 0.0), scale_keyframes=[
            [_kf(0, 2.0), _kf(10, 2.0)], [], [],
        ])
        # Animation B keeps the bone hidden throughout.
        track_b = _make_track(0, "Hidden", (0.0, 0.0, 0.0), scale_keyframes=[
            [_kf(0, 0.0), _kf(10, 0.0)], [], [],
        ])
        anims = [
            IRBoneAnimationSet(name="A", tracks=[track_a]),
            IRBoneAnimationSet(name="B", tracks=[track_b]),
        ]

        fix_near_zero_bone_matrices(bones, anims)

        # Both tracks' rest_local_matrix should encode visible scale X=2, Y=1, Z=1.
        expected = matrix_to_list(compile_srt_matrix((2.0, 1.0, 1.0), (0, 0, 0), (0, 0, 0)))
        assert track_a.rest_local_matrix == expected
        assert track_b.rest_local_matrix == expected

    def test_descendant_cascade_through_intermediate_tiny_bone(self):
        """Grandchild's world propagates correctly even when the intermediate
        parent is tiny with no visible scale in any animation."""
        # Root (normal) → Middle (tiny, no animation) → Child (normal, offset by X=5).
        bones = [
            _make_bone("Root", None, (1.0, 1.0, 1.0)),
            _make_bone("Middle", 0, (0.0, 0.0, 0.0)),
            _make_bone("Child", 1, (1.0, 1.0, 1.0), position=(5.0, 0.0, 0.0)),
        ]
        _recompute_world_cascade(bones)

        # Before the fix, Middle's world is zeroed, so Child's world is also zeroed.
        # (confirm the starting state to make the regression explicit)
        pre_child_world = Matrix(bones[2].world_matrix)
        assert pre_child_world.to_translation().length < 1e-6

        fix_near_zero_bone_matrices(bones, [])

        # After the fix, Middle should be rebound to identity and Child's world
        # should sit at (5, 0, 0) — inherited through the rebound intermediate.
        child_world = Matrix(bones[2].world_matrix)
        child_translation = child_world.to_translation()
        assert abs(child_translation.x - 5.0) < 1e-5
        assert abs(child_translation.y) < 1e-5
        assert abs(child_translation.z) < 1e-5

    def test_no_near_zero_bones_is_a_noop(self):
        """Function returns cleanly when there are no tiny-rest bones."""
        bones = [_make_bone("Root", None, (1.0, 1.0, 1.0))]
        original = list(bones[0].world_matrix)
        fix_near_zero_bone_matrices(bones, [])
        assert bones[0].world_matrix == original

    def test_descendant_local_matrix_recomputed_with_rebound_parent_scl(self):
        """Regression: descendants of a near-zero bone need local_matrix
        rebuilt with the rebound parent_scl, not left as computed against the
        original tiny accumulated scale (which produces huge correction terms
        like ``mtx[i][j] *= parent_scl[j] / parent_scl[i]`` with tiny i).

        Before the fix, a descendant with non-uniform own-scale under a
        partially-tiny ancestor produced world columns in the tens-of-thousands.
        """
        try:
            from shared.Constants.hsd import JOBJ_CLASSICAL_SCALING
        except (ImportError, SystemError):
            JOBJ_CLASSICAL_SCALING = (1 << 3)

        # Root (unit), near-zero shoulder with one intact axis (Y), unit middle,
        # non-uniform leaf (mirrors subame Bone_068 → 070 → 076 chain).
        bones = [
            _make_bone("Root", None, (1.0, 1.0, 1.0)),
            _make_bone("Shoulder", 0, (1e-5, 1.0, 1e-5)),
            _make_bone("Middle", 1, (1.0, 1.0, 1.0), position=(0.05, 0.0, 0.0)),
            _make_bone("Leaf", 2, (1.221, 0.549, 1.0), position=(0.04, -0.07, -0.04)),
        ]
        # Reproduce the original describe_bones pipeline: compute local_matrix
        # via compile_srt_matrix with parent_scl = accumulated parent chain.
        accum = [None] * len(bones)
        for i, b in enumerate(bones):
            parent_scl = None
            if b.parent_index is not None:
                parent_scl = accum[b.parent_index]
            if parent_scl is None:
                accum[i] = b.scale
            elif b.flags & JOBJ_CLASSICAL_SCALING:
                accum[i] = parent_scl
            else:
                accum[i] = tuple(b.scale[c] * parent_scl[c] for c in range(3))
            local = compile_srt_matrix(b.scale, b.rotation, b.position, parent_scl)
            if b.parent_index is None:
                world = local
            else:
                world = Matrix(bones[b.parent_index].world_matrix) @ local
            b.local_matrix = matrix_to_list(local)
            b.world_matrix = matrix_to_list(world)
            b.accumulated_scale = accum[i]

        # Anim: shoulder toggles hidden → visible (scale 1.0 in channel X and Z)
        shoulder_track = _make_track(1, "Shoulder", (1e-5, 1.0, 1e-5), scale_keyframes=[
            [_kf(0, 1.0), _kf(10, 0.0)],
            [_kf(0, 1.0), _kf(10, 1.0)],
            [_kf(0, 1.0), _kf(10, 0.0)],
        ])
        anims = [IRBoneAnimationSet(name="A", tracks=[shoulder_track])]

        fix_near_zero_bone_matrices(bones, anims)

        # Leaf world columns must be bounded — pre-fix these were ~1e5 in Y.
        leaf_world = bones[3].world_matrix
        for c in range(3):
            col = (leaf_world[0][c]**2 + leaf_world[1][c]**2 + leaf_world[2][c]**2) ** 0.5
            assert col < 10.0, f"Leaf world column {c} magnitude {col} — rebind didn't cascade to descendant local_matrix"

