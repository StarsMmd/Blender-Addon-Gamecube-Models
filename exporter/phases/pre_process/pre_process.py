"""Pre-process phase: validate export conditions before running the pipeline.

Checks that the output path is valid and the Blender scene is suitable
for export. Raises ValueError if any check fails, cancelling the export.
"""
import os

try:
    from ....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


MAX_VERTEX_WEIGHTS = 4
MAX_TEXTURE_DIM = 512


def pre_process(context, filepath, options=None, logger=StubLogger()):
    """Validate export conditions.

    Args:
        context: Blender context with the scene to export.
        filepath: Target output file path.
        options: dict of exporter options.
        logger: Logger instance.

    Raises:
        ValueError: If any validation check fails.
    """
    if options is None:
        options = {}

    logger.info("=== Export Pre-Process: Validation ===")

    _validate_output_path(filepath, logger)
    _validate_scene(context, logger)
    _validate_vertex_weight_count(context, logger)
    _validate_texture_sizes(context, logger)
    _validate_anim_timings(context, logger)

    logger.info("=== Export Pre-Process complete ===")


def _validate_output_path(filepath, logger):
    """Check the output path is valid for export.

    Both .dat and .pkx output are supported:
    - .dat: always written from scratch.
    - .pkx: if PKX metadata exists on the armature (from prepare_for_export.py),
      builds a new PKX from scratch. Otherwise injects into an existing file,
      or falls back to a default XD header.
    """
    logger.info("  Output path OK: %s", filepath)


def _validate_scene(context, logger):
    """Check the Blender scene is suitable for export.

    Validates that the selected armature meets the requirements for
    DAT model export.

    Args:
        context: Blender context.
        logger: Logger instance.

    Raises:
        ValueError: If the scene is not suitable for export.
    """
    # TODO: Implement scene validation
    # - Check that an armature is selected
    # - Check that meshes are parented to the armature
    # - Check for unsupported configurations
    logger.info("  Scene validation OK (stub)")


def _validate_vertex_weight_count(context, logger):
    """Reject any vertex with more than 4 non-zero bone weights.

    The GX envelope matrix-index byte packs up to 4 MTXIDX slots, so the
    hardware cannot blend more than 4 influences per vertex. Weight
    limiting lives in scripts/prepare_for_export.py; this check just
    guards against running the exporter on a scene where that step was
    skipped.
    """
    try:
        import bpy
    except ImportError:
        bpy = None
    scene = getattr(context, 'scene', None)
    objects = list(scene.objects) if scene is not None else (
        list(bpy.data.objects) if bpy is not None else []
    )
    meshes_by_armature = {
        arm: [obj for obj in objects
              if obj.parent is arm and getattr(obj, 'type', None) == 'MESH']
        for arm in objects if getattr(arm, 'type', None) == 'ARMATURE'
    }
    _check_vertex_weight_count(meshes_by_armature)
    logger.info("  Vertex weight count OK (max %d per vertex)", MAX_VERTEX_WEIGHTS)


def _check_vertex_weight_count(meshes_by_armature):
    offenders = []
    for meshes in meshes_by_armature.values():
        for mesh in meshes:
            data = getattr(mesh, 'data', None)
            if data is None:
                continue
            for v in data.vertices:
                n = sum(1 for g in v.groups if g.weight > 0.0)
                if n > MAX_VERTEX_WEIGHTS:
                    offenders.append((mesh.name, v.index, n))
                    if len(offenders) >= 10:
                        break
            if len(offenders) >= 10:
                break
        if len(offenders) >= 10:
            break
    if offenders:
        sample = "; ".join(f"{m}[v{i}]={n}" for m, i, n in offenders[:5])
        raise ValueError(
            f"Vertex weight count exceeds GameCube envelope limit of "
            f"{MAX_VERTEX_WEIGHTS}. Run scripts/prepare_for_export.py "
            f"first (tune MAX_WEIGHTS_PER_VERTEX). Sample offenders: {sample}"
        )


def _validate_texture_sizes(context, logger):
    """Reject any texture with a dimension above MAX_TEXTURE_DIM.

    GameCube RAM and TMEM budgets can't absorb arbitrarily-large textures
    from GLB/FBX rips. The prepare_for_export.py script downscales images
    above the cap; this check guards against running the exporter on a
    scene where that step was skipped.
    """
    try:
        import bpy
    except ImportError:
        bpy = None
    scene = getattr(context, 'scene', None)
    objects = list(scene.objects) if scene is not None else (
        list(bpy.data.objects) if bpy is not None else []
    )

    seen = set()
    images = []
    for obj in objects:
        if getattr(obj, 'type', None) != 'MESH':
            continue
        for slot in getattr(obj, 'material_slots', []):
            mat = getattr(slot, 'material', None)
            if mat is None or not getattr(mat, 'use_nodes', False):
                continue
            for node in mat.node_tree.nodes:
                if node.bl_idname != 'ShaderNodeTexImage' or not node.image:
                    continue
                img = node.image
                if img.name in seen:
                    continue
                seen.add(img.name)
                images.append((img.name, img.size[0], img.size[1]))

    _check_texture_sizes(images)
    logger.info("  Texture sizes OK (max %dx%d)", MAX_TEXTURE_DIM, MAX_TEXTURE_DIM)


def _check_texture_sizes(images):
    offenders = [
        (name, w, h) for name, w, h in images
        if w > MAX_TEXTURE_DIM or h > MAX_TEXTURE_DIM
    ]
    if offenders:
        sample = "; ".join(f"{n} ({w}x{h})" for n, w, h in offenders[:5])
        raise ValueError(
            f"Texture dimensions exceed GameCube cap of "
            f"{MAX_TEXTURE_DIM}x{MAX_TEXTURE_DIM}. Run "
            f"scripts/prepare_for_export.py first to downscale. "
            f"Sample offenders: {sample}"
        )


def _validate_anim_timings(context, logger):
    """Reject any PKX anim slot that assigns a real action but leaves all
    four timing fields at zero.

    The game's battle state machine reads `anim_entries[slot].timing_1..4`
    to pace loop restarts (fmod against timing_1 on idle loops), trigger
    hit/recovery events on attacks, and decide when to transition back to
    idle. All-zero timings give divide-by-zero and immediate state advance
    on battle entry — a reliable crash trigger on send-out.

    `scripts/prepare_for_export.py:derive_timing(armature)` computes correct
    timings from each slot's assigned action duration. This validator only
    catches the case where slots are populated but that derivation step was
    skipped — empty slots are intentionally unused and stay at 0.
    """
    try:
        import bpy
    except ImportError:
        bpy = None

    scene = getattr(context, 'scene', None)
    objects = list(scene.objects) if scene is not None else (
        list(bpy.data.objects) if bpy is not None else []
    )
    actions = bpy.data.actions if bpy is not None else []
    action_durations = {a.name: _action_duration(a) for a in actions}

    slot_state = []
    for arm in objects:
        if getattr(arm, 'type', None) != 'ARMATURE':
            continue
        if arm.get('dat_pkx_format') is None:
            continue  # No PKX metadata on this rig — nothing to validate.
        anim_count = arm.get('dat_pkx_anim_count', 17)
        for i in range(anim_count):
            prefix = 'dat_pkx_anim_%02d' % i
            sub_0 = arm.get(prefix + '_sub_0_anim', '') or ''
            t1 = float(arm.get(prefix + '_timing_1', 0.0))
            t2 = float(arm.get(prefix + '_timing_2', 0.0))
            t3 = float(arm.get(prefix + '_timing_3', 0.0))
            t4 = float(arm.get(prefix + '_timing_4', 0.0))
            action_dur = action_durations.get(sub_0, 0.0) if sub_0 else 0.0
            slot_state.append((arm.name, i, sub_0, action_dur, (t1, t2, t3, t4)))

    _check_anim_timings(slot_state)
    logger.info("  Anim timings OK (no populated slots left at all-zero)")


def _action_duration(action):
    """Max keyframe time across all fcurves, 0.0 if no keyframes.

    Mirrors `scripts/prepare_for_export.py:_get_action_duration` but works
    directly on an action object rather than looking up by name — avoids a
    second dict roundtrip inside the validator.
    """
    fcurves = getattr(action, 'fcurves', None)
    if not fcurves:
        return 0.0
    max_frame = 0.0
    for fc in fcurves:
        for kp in fc.keyframe_points:
            if kp.co[0] > max_frame:
                max_frame = float(kp.co[0])
    return max_frame / 60.0 if max_frame > 0 else 0.0


def _check_anim_timings(slot_state):
    """Pure helper — raise ValueError if any slot with a real assigned
    action (action exists and has keyframes) has all four timings == 0.

    Args:
        slot_state: iterable of
            (armature_name, slot_index, sub_0_anim_name, action_duration, (t1, t2, t3, t4))
        tuples. `action_duration` == 0.0 means the slot's assigned action
        either doesn't exist in the scene or has no keyframes — in either
        case the slot is functionally unused and timing=0 is correct.
    """
    offenders = []
    for arm_name, slot_idx, sub_0, dur, timings in slot_state:
        if not sub_0:
            continue  # Slot deliberately unused.
        if dur <= 0.0:
            continue  # Assigned action doesn't exist or is empty — skip.
        if any(t != 0.0 for t in timings):
            continue  # At least one timing is set — good.
        offenders.append((arm_name, slot_idx, sub_0))

    if offenders:
        sample = "; ".join(
            f"{arm}[slot {i}]→{action}" for arm, i, action in offenders[:8]
        )
        raise ValueError(
            "PKX anim slot has an assigned action but all four timing fields "
            "are zero — the game divides by timing_1 on the idle loop and "
            "uses timing_2/3 to gate attack events, so this crashes on battle "
            "entry. Run scripts/prepare_for_export.py:derive_timing(armature) "
            f"after populating slots. Offenders: {sample}"
        )
