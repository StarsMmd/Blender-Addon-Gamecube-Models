"""IR animation sets → BR actions + the per-frame GX pose bake.

Every animated bone is posed by one mechanism — ``bake_frame`` composes its
exact GX world for the frame and rebases it against the normalized edit-bone
rest; build drops that target onto the pose bone and lets Blender invert its own
``inherit_scale`` formula. The bake is the default because it reproduces GX for
*every* bone (non-uniform, near-zero, animated scale) without special cases.

``inherit_scale`` then decides only how the identical target is read back:

* **NONE** (default / baked): the safe universal inverse. Used for any bone in
  the ``scale_baked_indices`` closure — its own or an ancestor's accumulated
  rest scale is non-uniform, or its (or an ancestor's) scale is animated.

* **ALIGNED** (the obvious cases): bones with a uniform, un-animated rest scale
  and no such ancestor. There the read-back is a sparse, mostly-identity scale
  channel and native inheritance works when hand-editing — but the pose still
  came from the same bake, so it stays exact.

The bake is pure (``math_shim`` only, no bpy) so it unit-tests against
``compile_srt_matrix`` chains without Blender.
"""

try:
    from .....shared.BR.actions import (
        BRAction, BRBoneTrack, BRMaterialTrack, BRBakeBone, BRBakeSkeleton,
    )
    from .....shared.helpers.math_shim import (
        Matrix, Vector, compile_srt_matrix, matrix_to_list,
    )
    from .....shared.Constants.hsd import JOBJ_CLASSICAL_SCALING
except (ImportError, SystemError):
    from shared.BR.actions import (
        BRAction, BRBoneTrack, BRMaterialTrack, BRBakeBone, BRBakeSkeleton,
    )
    from shared.helpers.math_shim import (
        Matrix, Vector, compile_srt_matrix, matrix_to_list,
    )
    from shared.Constants.hsd import JOBJ_CLASSICAL_SCALING


_NEAR_ZERO_SCALE = 1e-6
_UNIFORM_RATIO = 1.1  # max/min accumulated-scale ratio still treated as uniform
# Floor for accumulated-scale magnitudes during composition. When an animation
# collapses a bone to exactly zero scale (a "hidden" frame), the composed world
# column becomes exactly zero and the NONE inversion of any descendant turns
# singular (basis blows up). Flooring to a small epsilon keeps directions
# defined so the `1/pscale · pscale` cancellation stays bounded, while ε is
# small enough that the subtree still collapses visually.
_MIN_SCALE = 1e-4


# ---------------------------------------------------------------------------
# IR anim sets → BR actions (keyframes only).
# ---------------------------------------------------------------------------


def plan_actions(ir_anim_sets, ir_bones):
    """Convert a list of IRBoneAnimationSet into BRAction list.

    In: ir_anim_sets (list[IRBoneAnimationSet]); ir_bones (list[IRBone], unused
        here — the bake reads rest data from the shared BRBakeSkeleton).
    Out: list[BRAction], one per input anim set, in the same order.
    """
    return [_plan_single_action(anim_set) for anim_set in ir_anim_sets]


def _plan_single_action(anim_set):
    """Convert one IRBoneAnimationSet into a BRAction with bone + material tracks."""
    bone_tracks = [_plan_bone_track(track) for track in anim_set.tracks]
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


def _plan_bone_track(ir_track):
    """Convert one IRBoneTrack into a BRBoneTrack (keyframes + rest constants)."""
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
        spline_path=ir_track.spline_path,
    )


# ---------------------------------------------------------------------------
# Model-wide rest data + the ALIGNED/NONE partition.
# ---------------------------------------------------------------------------


def build_bake_skeleton(ir_bones, ir_anim_sets=()):
    """Build the model-wide BRBakeSkeleton the per-frame pose bake consumes.

    In: ir_bones (list[IRBone]); ir_anim_sets (iterable[IRBoneAnimationSet],
        scanned so scale-animated bones read back under NONE).
    Out: BRBakeSkeleton with per-bone rest data, a parent-first bone order, and
         the precomputed ``scale_baked_indices`` closure.
    """
    bones = [
        BRBakeBone(
            name=b.name,
            parent_index=b.parent_index,
            rest_scale=tuple(b.scale),
            rest_rotation=tuple(b.rotation),
            rest_position=tuple(b.position),
            rest_world_matrix=[list(row) for row in b.world_matrix],
            normalized_rest_matrix=[list(row) for row in b.normalized_world_matrix],
            accumulated_scale=tuple(b.accumulated_scale),
            classical_scaling=bool(b.flags & JOBJ_CLASSICAL_SCALING),
        )
        for b in ir_bones
    ]
    dfs_order = _parent_first_order(bones)
    seed = _scale_animated_bones(ir_anim_sets)
    closure = _scale_baked_closure(bones, dfs_order, seed)
    return BRBakeSkeleton(bones=bones, dfs_order=dfs_order,
                          scale_baked_indices=sorted(closure))


def scale_baked_indices(skeleton):
    """Bones that must read back under NONE rather than native ALIGNED.

    In: skeleton (BRBakeSkeleton).
    Out: set[int].
    """
    return set(skeleton.scale_baked_indices)


def _scale_animated_bones(ir_anim_sets):
    """Bone indices whose scale is keyframed in any action.

    Native ALIGNED inheritance can't represent a non-uniform scale, and an
    animated scale can pass through non-uniform values between keyframes that a
    pure-plan check can't rule out. So any scale-animated bone reads back under
    NONE; ALIGNED is reserved for bones whose scale is a constant, uniform rest.

    In: ir_anim_sets (iterable[IRBoneAnimationSet]).
    Out: set[int].
    """
    seed = set()
    for anim_set in ir_anim_sets:
        for track in anim_set.tracks:
            if any(track.scale):
                seed.add(track.bone_index)
    return seed


def _scale_baked_closure(bones, dfs_order, seed):
    """Descendant-closure of the baked seed over a bone list.

    A bone reads back under NONE if its rest accumulated scale is non-uniform,
    it is seeded (scale-animated), or any ancestor is — so an ALIGNED bone never
    sits under a bone whose non-uniform scale it would inherit incorrectly.

    In: bones (list[BRBakeBone]); dfs_order (list[int], parent-first);
        seed (set[int]).
    Out: set[int].
    """
    baked = set()
    for idx in dfs_order:
        bone = bones[idx]
        parent = bone.parent_index
        if (_is_nonuniform(bone.accumulated_scale)
                or idx in seed
                or (parent is not None and parent in baked)):
            baked.add(idx)
    return baked


def _parent_first_order(bones):
    """Return bone indices ordered so every parent precedes its children."""
    children = {}
    roots = []
    for i, b in enumerate(bones):
        if b.parent_index is None:
            roots.append(i)
        else:
            children.setdefault(b.parent_index, []).append(i)
    order = []
    stack = list(reversed(roots))
    while stack:
        i = stack.pop()
        order.append(i)
        for c in reversed(children.get(i, ())):
            stack.append(c)
    # Fall back to raw index order for any bone unreachable from a root
    # (defensive — a cyclic/dangling parent_index should never occur).
    if len(order) != len(bones):
        seen = set(order)
        order.extend(i for i in range(len(bones)) if i not in seen)
    return order


# ---------------------------------------------------------------------------
# Per-frame pose bake — pure math (math_shim only), no bpy.
# ---------------------------------------------------------------------------


def bake_frame(skeleton, frame_srts, bake_indices):
    """Compose each bone's GX world for one frame; return the mesh-correct
    *target* pose (armature space) for every bone in ``bake_indices``.

    GX's world for a bone is ``Rot(bone) · diag(accumulated_scale)``; we rebase
    it against the normalized edit-bone rest so build can drop it straight onto
    the pose bone (``pose_bone.matrix = target``) and let Blender perform the
    inversion for the bone's ``inherit_scale`` mode (ALIGNED or NONE). The
    inversion stays in bpy on purpose — Blender's bone-space translation
    conventions (bone length / roll) are impractical to reproduce exactly in
    pure math, and its own setter is self-consistent with its evaluator. The
    target world is identical for either mode; only the recovered basis differs.

    In: skeleton (BRBakeSkeleton); frame_srts (dict[int, (scale, rotation,
        location)] for animated bones; bones absent use their rest SRT);
        bake_indices (iterable[int], bones to emit a target for).
    Out: dict[int, list[list[float]]] — 4x4 target world per baked bone.
    """
    gx_world = {}   # bone_index -> Matrix (armature-space GX world)
    gx_accum = {}   # bone_index -> accumulated scale tuple
    gx_rot = {}     # bone_index -> Matrix (pure rotation chain, no scale)
    targets = {}
    want = set(bake_indices)

    for idx in skeleton.dfs_order:
        bone = skeleton.bones[idx]
        parent = bone.parent_index

        if idx in frame_srts:
            scale, rotation, location = frame_srts[idx]
        else:
            # Un-animated bone: compose from its rest local so it still follows
            # an animated ancestor. Use the rebound-consistent local scale
            # (accumulated_scale ratio) rather than the raw rest scale, so the
            # rest composition reproduces world_matrix and near-zero bones stay
            # at their rebound-visible size.
            scale = _rest_local_scale(bone, skeleton.bones[parent] if parent is not None else None)
            rotation = bone.rest_rotation
            location = bone.rest_position

        world, accum, rot = _compose_gx(
            scale, rotation, location,
            gx_world.get(parent), gx_accum.get(parent), gx_rot.get(parent),
            bone.classical_scaling,
        )
        gx_world[idx] = world
        gx_accum[idx] = accum
        gx_rot[idx] = rot

        if idx in want:
            norm_rest = Matrix(bone.normalized_rest_matrix)
            rest_world_inv = Matrix(bone.rest_world_matrix).inverted_safe()
            targets[idx] = matrix_to_list(world @ rest_world_inv @ norm_rest)

    return targets


def compute_bake_plan(skeleton, animated_indices):
    """Decide which bones the bake must pose and group them by depth.

    A bone is posed if it is animated OR it is in the baked closure
    (``scale_baked_indices``). Baked bones can't ride native inheritance, so
    they are posed even when un-animated (a still hand on a non-uniformly-scaled
    arm); animated aligned bones are posed too and read back under ALIGNED so
    their scale stays inheritance-sparse. Un-animated aligned bones need no
    explicit pose — their rest edit bone + ALIGNED inheritance suffice.

    In: skeleton (BRBakeSkeleton); animated_indices (set[int]).
    Out: (bake_indices sorted list[int], depth_levels list[list[int]]) where
         depth_levels[d] holds the posed bone indices at chain depth d
         (parent-before-child so build can update the pose one level at a time).
    """
    bake = set(animated_indices) | scale_baked_indices(skeleton)
    depth = [0] * len(skeleton.bones)
    for i in skeleton.dfs_order:
        p = skeleton.bones[i].parent_index
        depth[i] = 0 if p is None else depth[p] + 1
    max_depth = max(depth) if depth else 0
    levels = [[] for _ in range(max_depth + 1)]
    for i in sorted(bake):
        levels[depth[i]].append(i)
    return sorted(bake), levels


def _is_nonuniform(accum):
    """True when an accumulated scale is non-uniform enough to defeat ALIGNED."""
    nonzero = [abs(x) for x in accum if abs(x) > _NEAR_ZERO_SCALE]
    if not nonzero:
        return False
    return max(abs(x) for x in accum) / min(nonzero) > _UNIFORM_RATIO


def _rest_local_scale(bone, parent_bone):
    """The bone's local scale for rest composition = accumulated ⊘ parent
    accumulated (component-wise). Equals the raw rest scale for clean bones,
    and the rebound-visible local scale for near-zero bones."""
    if parent_bone is None:
        return tuple(bone.accumulated_scale)
    pa = parent_bone.accumulated_scale
    return tuple(bone.accumulated_scale[c] / _signed_denominator(pa[c]) for c in range(3))


def _signed_denominator(value):
    """Clamp a denominator away from zero, preserving sign."""
    if abs(value) >= _MIN_SCALE:
        return value
    return _MIN_SCALE if value >= 0.0 else -_MIN_SCALE


def _compose_gx(scale, rotation, location, parent_world, parent_accum, parent_rot,
                classical_scaling):
    """Compose a bone's GX world directly (division-free).

    GX's aligned-scale correction (``compile_srt_matrix``'s ``a_j/a_i``) is
    singular when a parent accumulated-scale component is zero, but that
    singularity cancels in the final world — which is always finite,
    ``Rot(bone) · diag(accumulated_scale)``. We build it from that closed form
    instead of the correction, so animated collapse-to-zero scales (hidden
    bones) don't divide by zero.

    In: scale/rotation/location (tuple[float,3]) the bone's animated SRT this
        frame; parent_world/parent_accum/parent_rot (Matrix / tuple / Matrix or
        None for roots); classical_scaling (bool).
    Out: (Matrix world, tuple accumulated_scale, Matrix pure-rotation chain).
    """
    r_own = compile_srt_matrix((1.0, 1.0, 1.0), rotation, (0.0, 0.0, 0.0))
    if parent_world is None:
        rot = r_own
        accum = tuple(scale)
        head = Vector(location)
    else:
        rot = parent_rot @ r_own
        accum = (tuple(parent_accum) if classical_scaling
                 else tuple(scale[c] * parent_accum[c] for c in range(3)))
        head = parent_world @ Vector(location)
    accum = tuple(_floor_scale(a) for a in accum)
    world_linear = rot @ _scale_matrix(accum)
    return _with_translation(world_linear, head), accum, rot


def _floor_scale(value):
    """Clamp a scale magnitude away from exactly zero, preserving sign."""
    if abs(value) >= _MIN_SCALE:
        return value
    return _MIN_SCALE if value >= 0.0 else -_MIN_SCALE


def _scale_matrix(s):
    return Matrix([
        [s[0], 0.0, 0.0, 0.0],
        [0.0, s[1], 0.0, 0.0],
        [0.0, 0.0, s[2], 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ])


def _with_translation(m, head):
    """Return a copy of 4x4 ``m`` with its translation column set to ``head``.

    math_shim's Matrix has a read-only ``.translation``, so rebuild from a list.
    """
    rows = [[m[i][j] for j in range(4)] for i in range(4)]
    rows[0][3] = head[0]
    rows[1][3] = head[1]
    rows[2][3] = head[2]
    return Matrix(rows)
