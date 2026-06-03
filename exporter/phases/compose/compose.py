"""Phase 2 (Export): Convert IRScene back to node trees.

Takes an IRScene (the platform-agnostic intermediate representation) and
reconstructs the SysDolphin node tree structure that can be serialized
to a .dat binary by DATBuilder.

Supports: skeleton (Joint tree), meshes (Mesh/PObject chains), materials,
animations, and lights.
"""
try:
    from ....shared.Nodes.Classes.Joints.ModelSet import ModelSet
    from ....shared.Nodes.Classes.RootNodes.SceneData import SceneData
    from ....shared.Nodes.Classes.RootNodes.BoundBox import BoundBox
    from ....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Joints.ModelSet import ModelSet
    from shared.Nodes.Classes.RootNodes.SceneData import SceneData
    from shared.Nodes.Classes.RootNodes.BoundBox import BoundBox
    from shared.helpers.logger import StubLogger

from .helpers.bones import compose_bones
from .helpers.meshes import compose_meshes
from .helpers.animations import compose_bone_animations
from .helpers.material_animations import compose_material_animations
from .helpers.lights import compose_lights
from .helpers.cameras import compose_camera
from .helpers.constraints import compose_constraints
from .helpers.scale import scale_scene_to_gc_units
# compose_particles exists but is NOT wired into the export pipeline — see
# the README "Particles (GPT1)" section for why export is disabled.


def compose_scene(ir_scene, options=None, logger=StubLogger()):
    """Convert an IRScene into node trees ready for serialization.

    Args:
        ir_scene: IRScene from the describe phase.
        options: dict of exporter options (reserved for future use).
        logger: Logger instance.

    Returns:
        (root_nodes, section_names) — lists of root nodes and their
        corresponding section names for DATBuilder.
    """
    if options is None:
        options = {}

    logger.info("=== Export Phase 2: Compose ===")

    # One-shot meters → GC units conversion. Everything downstream
    # (bones, meshes, animations, bound box, cameras, lights) reads the
    # IR after this call and therefore operates in GC units uniformly —
    # no helper needs to remember to apply METERS_TO_GC of its own.
    scale_scene_to_gc_units(ir_scene)

    root_nodes = []
    section_names = []

    for mi, model in enumerate(ir_scene.models):
        logger.info("  Composing model '%s' (%d bones, %d meshes)",
                    model.name, len(model.bones), len(model.meshes))

        root_joint, joints = compose_bones(model.bones, logger)
        if root_joint is None:
            logger.info("    Skipped: no bones")
            continue

        compose_meshes(model.meshes, joints, model.bones, logger)

        # Strip node names if requested (for round-trip testing against
        # original models that have empty name fields)
        if options.get('strip_names', False):
            for joint in joints:
                joint.name = None

        # Compose constraints (must happen before animations — sets joint type flags)
        compose_constraints(model, joints, model.bones, logger)

        # Compose animations
        anim_roots = compose_bone_animations(
            model.bone_animations, joints, model.bones, logger)

        # Compose material animations
        mat_anim_roots = None
        if model.bone_animations:
            mat_roots = []
            for anim_set in model.bone_animations:
                if anim_set.material_tracks:
                    root = compose_material_animations(anim_set, model.bones, model.meshes, logger)
                    if root:
                        mat_roots.append(root)
            mat_anim_roots = mat_roots if mat_roots else None

        model_set = ModelSet(address=None, blender_obj=None)
        model_set.root_joint = root_joint
        model_set.animated_joints = anim_roots
        model_set.animated_material_joints = mat_anim_roots
        model_set.animated_shape_joints = None

        scene_data = SceneData(address=None, blender_obj=None)
        scene_data.models = [model_set]
        scene_data.camera = compose_camera(ir_scene.cameras[0], logger) if ir_scene.cameras else None
        scene_data.lights = compose_lights(ir_scene.lights, logger=logger)
        scene_data.fog = None

        root_nodes.append(scene_data)
        section_names.append('scene_data')

        # Bound box — per-frame AABBs across all animation sets
        if options.get('include_bound_box', True):
            bb = _compose_bound_box(model, logger)
            if bb:
                root_nodes.append(bb)
                section_names.append('bound_box')
        else:
            logger.info("  Bound box: skipped (disabled in export options)")

    logger.info("=== Export Phase 2 complete: %d scene(s) ===", len(root_nodes))

    return root_nodes, section_names


def _compose_bound_box(model, logger):
    """Create a BoundBox node with one true skinned AABB per frame.

    Game-native PKXs ship one AABB per animation frame, updated to
    reflect skeletal deformation each frame. We compute the tight AABB
    by running linear-blend skinning on every mesh vertex at every
    frame of every animation set. For each vertex-bone pair we
    pre-compute `inv_bind[bone] @ vertex_rest_world`, then per frame
    combine those with the bones' animated world matrices.

    Returns BoundBox node or None if no meshes.
    """
    import struct
    try:
        from ....shared.helpers.math_shim import Matrix
        from ....shared.IR.enums import SkinType
    except (ImportError, SystemError):
        from shared.helpers.math_shim import Matrix
        from shared.IR.enums import SkinType

    if not model.meshes:
        return None

    skin_samples = _build_skin_samples(model, SkinType)
    if not skin_samples:
        return None

    anim_sets = model.bone_animations or []
    anim_count = max(1, len(anim_sets))

    aabb_blobs = []
    frame_counts = []

    if not anim_sets:
        rest_world = _rest_bone_world_matrices(model)
        mn, mx = _compute_skinned_aabb(skin_samples, rest_world)
        aabb_blobs.append(struct.pack('>ffffff', mn[0], mn[1], mn[2], mx[0], mx[1], mx[2]))
        frame_counts.append(1)
    else:
        for anim_set in anim_sets:
            max_ef = max((int(t.end_frame) for t in anim_set.tracks), default=1)
            # Animation plays over inclusive range [0, end_frame], so emit
            # (end_frame + 1) AABBs per set to match game-native PKXs.
            frame_count = max(1, max_ef + 1)
            frame_counts.append(frame_count)
            for f in range(frame_count):
                world = _animated_bone_world_matrices(model, anim_set, f)
                mn, mx = _compute_skinned_aabb(skin_samples, world)
                aabb_blobs.append(struct.pack('>ffffff',
                                              mn[0], mn[1], mn[2],
                                              mx[0], mx[1], mx[2]))

    raw_data = b''.join(aabb_blobs)
    bb = BoundBox(address=None, blender_obj=None)
    bb.anim_set_count = anim_count
    bb.first_anim_frame_count = frame_counts[0]
    bb.raw_aabb_data = raw_data

    total_frames = sum(frame_counts)
    logger.info("    Bound box: %d set(s), %d total frames (per-frame skinned, %d samples)",
                anim_count, total_frames, len(skin_samples))

    return bb


def _rest_bone_world_matrices(model):
    """Return per-bone rest world matrices as `Matrix` objects."""
    try:
        from ....shared.helpers.math_shim import Matrix
    except (ImportError, SystemError):
        from shared.helpers.math_shim import Matrix
    out = []
    for b in model.bones:
        if b.world_matrix:
            out.append(Matrix(b.world_matrix))
        else:
            out.append(Matrix.Identity(4))
    return out


def _build_skin_samples(model, SkinType):
    """Return one entry per mesh vertex: a list of
    `(bone_idx, weight, local_rest_Vector)` tuples.

    `local_rest = inv_bind[bone_idx] @ vertex_rest_world`. Skinning at
    frame f is then `sum_b weight_b * anim_world[b] @ local_rest_b`.
    Pre-computing `inv_bind @ vertex` here turns each per-frame vertex
    evaluation into one matrix-vector multiply per weight.
    """
    try:
        from ....shared.helpers.math_shim import Matrix, Vector
    except (ImportError, SystemError):
        from shared.helpers.math_shim import Matrix, Vector

    n_bones = len(model.bones)
    if n_bones == 0:
        return []

    bone_name_to_index = {b.name: i for i, b in enumerate(model.bones)}
    rest_world = _rest_bone_world_matrices(model)

    inv_bind = []
    for i, b in enumerate(model.bones):
        if b.inverse_bind_matrix:
            inv_bind.append(Matrix(b.inverse_bind_matrix))
        else:
            try:
                inv_bind.append(rest_world[i].inverted())
            except ValueError:
                inv_bind.append(Matrix.Identity(4))

    samples = []
    for mesh in model.meshes:
        bw = mesh.bone_weights

        weighted_map = None
        if bw and bw.type == SkinType.WEIGHTED and bw.assignments:
            weighted_map = {}
            for v_idx, pairs in bw.assignments:
                resolved = []
                total_w = 0.0
                for bone_name, w in pairs:
                    b_idx = bone_name_to_index.get(bone_name)
                    if b_idx is not None and w > 0.0:
                        resolved.append((b_idx, float(w)))
                        total_w += float(w)
                if resolved and total_w > 0.0:
                    # Normalise weights so the AABB isn't skewed by
                    # non-unit-sum assignments.
                    weighted_map[v_idx] = [(bi, w / total_w) for bi, w in resolved]

        default_bone = mesh.parent_bone_index if 0 <= mesh.parent_bone_index < n_bones else 0
        if bw and bw.type in (SkinType.SINGLE_BONE, SkinType.RIGID) and bw.bone_name:
            named = bone_name_to_index.get(bw.bone_name)
            if named is not None:
                default_bone = named

        for v_idx, v in enumerate(mesh.vertices):
            v_world = Vector((float(v[0]), float(v[1]), float(v[2])))
            entries = None
            if weighted_map is not None:
                assigned = weighted_map.get(v_idx)
                if assigned:
                    entries = [(bi, w, inv_bind[bi] @ v_world) for bi, w in assigned]
            if entries is None:
                entries = [(default_bone, 1.0, inv_bind[default_bone] @ v_world)]
            samples.append(entries)

    return samples


def _compute_skinned_aabb(skin_samples, world_matrices):
    """Reduce `skin_samples` against `world_matrices` → (min, max) tuples."""
    mn = [float('inf')] * 3
    mx = [float('-inf')] * 3
    for entries in skin_samples:
        if len(entries) == 1:
            b_idx, _w, lv = entries[0]
            p = world_matrices[b_idx] @ lv
            px, py, pz = p[0], p[1], p[2]
        else:
            px = py = pz = 0.0
            for b_idx, w, lv in entries:
                p = world_matrices[b_idx] @ lv
                px += w * p[0]
                py += w * p[1]
                pz += w * p[2]
        if px < mn[0]: mn[0] = px
        if px > mx[0]: mx[0] = px
        if py < mn[1]: mn[1] = py
        if py > mx[1]: mx[1] = py
        if pz < mn[2]: mn[2] = pz
        if pz > mx[2]: mx[2] = pz
    return mn, mx


def _eval_channel(keyframes, frame, default):
    """Linear interpolation of an IRKeyframe list at `frame`. Matches
    the game's HSD_FObjInterpretAnim behaviour (raw fadds between
    keyframes). Constant-clamped outside the key range."""
    if not keyframes:
        return default
    if len(keyframes) == 1:
        return keyframes[0].value
    if frame <= keyframes[0].frame:
        return keyframes[0].value
    if frame >= keyframes[-1].frame:
        return keyframes[-1].value
    # Walk to find the bracketing pair.
    for i in range(len(keyframes) - 1):
        a, b = keyframes[i], keyframes[i + 1]
        if a.frame <= frame <= b.frame:
            span = b.frame - a.frame
            if span <= 0:
                return a.value
            t = (frame - a.frame) / span
            return a.value + t * (b.value - a.value)
    return keyframes[-1].value


def _animated_bone_world_matrices(model, anim_set, frame):
    """Evaluate each bone's world-space transform at `frame` under
    `anim_set`. Returns a list of 4x4 Matrix objects (one per bone).

    Bones without a track in this anim_set fall back to their rest
    local SRT. Parent chain propagates via matrix multiplication.
    """
    try:
        from ....shared.helpers.math_shim import compile_srt_matrix
    except (ImportError, SystemError):
        from shared.helpers.math_shim import compile_srt_matrix

    track_by_bone = {t.bone_index: t for t in anim_set.tracks}
    world = [None] * len(model.bones)
    for i, bone in enumerate(model.bones):
        track = track_by_bone.get(i)
        if track is not None:
            rx = _eval_channel(track.rotation[0], frame, bone.rotation[0])
            ry = _eval_channel(track.rotation[1], frame, bone.rotation[1])
            rz = _eval_channel(track.rotation[2], frame, bone.rotation[2])
            lx = _eval_channel(track.location[0], frame, bone.position[0])
            ly = _eval_channel(track.location[1], frame, bone.position[1])
            lz = _eval_channel(track.location[2], frame, bone.position[2])
            sx = _eval_channel(track.scale[0], frame, bone.scale[0])
            sy = _eval_channel(track.scale[1], frame, bone.scale[1])
            sz = _eval_channel(track.scale[2], frame, bone.scale[2])
        else:
            rx, ry, rz = bone.rotation
            lx, ly, lz = bone.position
            sx, sy, sz = bone.scale
        local = compile_srt_matrix((sx, sy, sz), (rx, ry, rz), (lx, ly, lz))
        parent = bone.parent_index
        if parent is not None and 0 <= parent < i and world[parent] is not None:
            world[i] = world[parent] @ local
        else:
            world[i] = local
    return world


def _animated_bone_positions(model, anim_set, frame):
    """Thin wrapper over `_animated_bone_world_matrices` returning just
    the translation component of each bone's animated world matrix."""
    world = _animated_bone_world_matrices(model, anim_set, frame)
    return [(m[0][3], m[1][3], m[2][3]) for m in world]
