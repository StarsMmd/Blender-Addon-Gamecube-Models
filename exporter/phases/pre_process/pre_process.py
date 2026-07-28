"""Pre-process phase: validate export conditions before running the pipeline.

Checks that the output path is valid and the Blender scene is suitable
for export. Raises ValueError if any check fails, cancelling the export.
"""
import os
import re

try:
    from ....shared.helpers.logger import StubLogger
    from ....shared.helpers.fsys_writer import (
        is_fsys, parse_fsys_summary, find_model_entries, MODEL_TYPE_PKX,
    )
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger
    from shared.helpers.fsys_writer import (
        is_fsys, parse_fsys_summary, find_model_entries, MODEL_TYPE_PKX,
    )


MAX_VERTEX_WEIGHTS = 4
MAX_TEXTURE_DIM = 512
MAX_TEXTURES_PER_MATERIAL = 8  # GX_MAX_TEXMAP: hardware texgen/texmap units


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

    ext, fsys_inner_kind = _validate_output_path(filepath, logger)
    _validate_baked_transforms(context, logger)
    _validate_root_bone_orientation(context, logger)
    _validate_origin_bone_not_animated(context, logger)
    _validate_vertex_weight_count(context, logger)
    _validate_mesh_owner_disjoint_from_deformers(context, logger)
    _validate_texture_sizes(context, logger)
    _validate_material_texture_count(context, logger)
    _validate_pkx_metadata(context, ext, fsys_inner_kind, logger)
    _validate_animation_timing(context, ext, fsys_inner_kind, logger)

    logger.info("=== Export Pre-Process complete ===")


def _validate_output_path(filepath, logger):
    """Check the output path is valid for export.

    - .dat: always written from scratch.
    - .pkx: if PKX metadata exists on the armature, builds a new PKX from
      scratch. Otherwise injects into an existing file, or falls back to
      a default XD header.
    - .fsys: must be an existing file containing exactly one model entry
      (.dat or .pkx). The model entry will be replaced; all other entries
      are preserved verbatim.

    Returns (ext, fsys_inner_kind):
        ext: 'dat' | 'pkx' | 'fsys' (other extensions are treated as 'dat').
        fsys_inner_kind: 'dat' | 'pkx' for fsys outputs, else None.
    """
    ext = filepath.rsplit('.', 1)[-1].lower() if '.' in filepath else ''
    if ext == 'fsys':
        inner = _validate_fsys_target(filepath, logger)
        logger.info("  Output path OK: %s (FSYS, inner=%s)", filepath, inner)
        return ext, inner
    logger.info("  Output path OK: %s", filepath)
    return ext, None


def _validate_fsys_target(filepath, logger):
    """Validate the .fsys output target and return the inner model kind.

    Raises ValueError with a friendly message for each failed check.
    Returns 'pkx' or 'dat' identifying what kind of model entry will be
    replaced.
    """
    problems = []
    if not os.path.exists(filepath):
        problems.append(
            "FSYS output requires an existing archive to inject into "
            "(found no file at %s). Create the FSYS by running the game "
            "or use a tool such as GoD-Tool to author one, then re-export."
            % filepath
        )
        raise ValueError(_format_fsys_problems(filepath, problems))

    try:
        with open(filepath, 'rb') as f:
            raw = f.read()
    except OSError as e:
        raise ValueError("Could not read FSYS file at %s: %s" % (filepath, e))

    if not is_fsys(raw):
        problems.append(
            "File at %s does not begin with the 'FSYS' magic bytes — it "
            "isn't an FSYS archive." % filepath
        )
        raise ValueError(_format_fsys_problems(filepath, problems))

    try:
        entries = parse_fsys_summary(raw)
    except ValueError as e:
        raise ValueError("Could not parse FSYS at %s: %s" % (filepath, e))

    model_entries = find_model_entries(entries)
    if len(model_entries) == 0:
        problems.append(
            "FSYS at %s contains no model entries (.dat or .pkx). "
            "There is no model slot to replace." % filepath
        )
    elif len(model_entries) > 1:
        names = ", ".join(e.filename for e in model_entries)
        problems.append(
            "FSYS at %s contains %d model entries (%s). Exactly one "
            "model entry is required so the exporter can pick the slot "
            "to replace unambiguously."
            % (filepath, len(model_entries), names)
        )
    if problems:
        raise ValueError(_format_fsys_problems(filepath, problems))

    inner = model_entries[0]
    logger.info("  FSYS target OK: replacing %s entry '%s' (compressed=%s)",
                inner.model_kind, inner.filename, inner.is_compressed)
    return inner.model_kind


def _format_fsys_problems(filepath, problems):
    bullet = "\n  - "
    return ("Cannot export to FSYS at %s — fix the following:%s%s"
            % (filepath, bullet, bullet.join(problems)))


def _validate_pkx_metadata(context, ext, fsys_inner_kind, logger):
    """If we're emitting a PKX (directly or via FSYS), require an armature
    that carries the PKX header metadata custom properties.

    Without `dat_pkx_format`, `extract_pkx_header` returns None and the
    package phase would either fall back to a default XD header or fail
    to produce a usable PKX — neither is what the user asked for when
    they pointed at a real .pkx / .fsys-with-pkx target.
    """
    needs_pkx = (ext == 'pkx') or (ext == 'fsys' and fsys_inner_kind == MODEL_TYPE_PKX)
    if not needs_pkx:
        return

    try:
        import bpy
    except ImportError:
        bpy = None
    scene = getattr(context, 'scene', None)
    objects = list(scene.objects) if scene is not None else (
        list(bpy.data.objects) if bpy is not None else []
    )
    armatures = [o for o in objects if getattr(o, 'type', None) == 'ARMATURE']
    if not armatures:
        raise ValueError(
            "PKX output requires an armature with PKX header metadata, "
            "but the scene has no armature."
        )
    if not any(a.get('dat_pkx_format') in ('XD', 'COLOSSEUM') for a in armatures):
        names = ", ".join(a.name for a in armatures) or "<none>"
        raise ValueError(
            "PKX output requires an armature with PKX header metadata "
            "(custom property 'dat_pkx_format' set to 'XD' or "
            "'COLOSSEUM'). Run scripts/prepare_for_pkx_export.py against "
            "this .blend to populate the metadata. Armatures inspected: " + names
        )
    logger.info("  PKX metadata OK")


def _validate_baked_transforms(context, logger):
    """Reject scenes whose armature or child meshes carry a non-identity
    `matrix_world` — the SRT decompose path on the bone side and the plain
    matmul on the vertex side disagree about shear, so unbaked transforms
    let those two paths drift bone-by-bone down the chain.

    Both prep scripts (`scripts/prepare_for_pkx_export.py` and
    `scripts/prepare_for_dat_export.py`) bake everything into the data;
    this check guards against running the exporter on a scene that
    skipped that step.
    """
    try:
        import bpy
    except ImportError:
        bpy = None
    scene = getattr(context, 'scene', None)
    objects = list(scene.objects) if scene is not None else (
        list(bpy.data.objects) if bpy is not None else []
    )

    armatures = [o for o in objects if getattr(o, 'type', None) == 'ARMATURE']
    children_by_armature = {
        arm: [o for o in objects
              if getattr(o, 'parent', None) is arm and getattr(o, 'type', None) == 'MESH']
        for arm in armatures
    }
    _check_baked_transforms(armatures, children_by_armature)
    logger.info("  Baked transforms OK (armatures + child meshes at identity matrix_world)")


def _check_baked_transforms(armatures, children_by_armature):
    """Pure helper for `_validate_baked_transforms` — drives unit tests
    without needing a real `bpy.data.objects`."""
    bad_armatures = []
    bad_meshes = []
    for arm in armatures:
        if not _is_identity_matrix(arm.matrix_world):
            bad_armatures.append(arm.name)
        for child in children_by_armature.get(arm, ()):
            if not _is_identity_matrix(child.matrix_world):
                bad_meshes.append(child.name)

    if not bad_armatures and not bad_meshes:
        return

    parts = []
    if bad_armatures:
        sample = ", ".join(bad_armatures[:3])
        parts.append("%d armature(s) [%s%s]" % (
            len(bad_armatures), sample,
            "…" if len(bad_armatures) > 3 else "",
        ))
    if bad_meshes:
        sample = ", ".join(bad_meshes[:3])
        parts.append("%d mesh(es) [%s%s]" % (
            len(bad_meshes), sample,
            "…" if len(bad_meshes) > 3 else "",
        ))

    raise ValueError(
        "Scene has unbaked transforms on " + " and ".join(parts) + ". "
        "Every armature and child mesh must have an identity matrix_world "
        "before exporting, or the bone path (SRT decompose) and vertex "
        "path (matmul) drift apart. Fix with one of:\n"
        "  • Run scripts/prepare_for_pkx_export.py (PKX output) or\n"
        "    scripts/prepare_for_dat_export.py (bare .dat output) against this .blend\n"
        "  • In Blender: select the armature + meshes, "
        "Object > Apply > All Transforms"
    )


def _is_identity_matrix(m, tol=1e-5):
    for i in range(4):
        for j in range(4):
            expected = 1.0 if i == j else 0.0
            if abs(m[i][j] - expected) > tol:
                return False
    return True


# ---------------------------------------------------------------------------
# Root joint orientation
# ---------------------------------------------------------------------------
#
# The exported root JOBJ must have an identity rotation — every game-native
# model does. The game applies the root joint's own rotation as the model's
# base orientation and does NOT cancel it the way a full skinning solve
# does, so a non-identity root joint turns the whole model in-game (typically
# 90 deg) even though Blender renders it correctly. The exporter converts
# each bone's rest matrix through a Z-up -> Y-up rotation; the root joint
# comes out identity exactly when the root bone's effective rest orientation
# equals the inverse of that conversion. This mirrors that computation so the
# check is exact for both baked (Z-up) and importer-built (Y-up) rigs.

# Inverse of the Z-up -> Y-up coordinate rotation the plan phase applies
# (-90 deg about X). Kept in sync with
# `exporter/phases/plan/helpers/armature.py::_COORD_ROTATION_INV` (no
# cross-phase import — phases must not depend on each other).
_COORD_ROTATION_INV = [
    [1.0, 0.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0],
    [0.0, -1.0, 0.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]


def _mat4_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)]
            for i in range(4)]


def _has_identity_rotation(m4, tol=1e-4):
    """True if the rotation component of a 4x4 (scale/translation ignored)
    is the identity. Columns are normalised first so a uniform/non-uniform
    scale doesn't mask an axis-aligned rotation."""
    cols = []
    for c in range(3):
        v = (m4[0][c], m4[1][c], m4[2][c])
        n = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5 or 1.0
        cols.append((v[0] / n, v[1] / n, v[2] / n))
    for i in range(3):
        for j in range(3):
            expected = 1.0 if i == j else 0.0
            if abs(cols[j][i] - expected) > tol:
                return False
    return True


def _validate_root_bone_orientation(context, logger):
    """Reject scenes whose root bone would export a non-identity root JOBJ.

    The prep scripts do **not** adjust root orientation (an earlier
    in-place auto-normalize was reverted — it broke animated children), so
    this guard is the only line of defence. `_check_root_bone_orientation`
    raises with the manual fix; the in-game symptom it prevents is the
    whole model rendered turned 90 deg.
    """
    try:
        import bpy
    except ImportError:
        bpy = None
    scene = getattr(context, 'scene', None)
    objects = list(scene.objects) if scene is not None else (
        list(bpy.data.objects) if bpy is not None else []
    )
    armatures = [o for o in objects if getattr(o, 'type', None) == 'ARMATURE']

    specs = []
    for arm in armatures:
        bones = getattr(arm.data, 'bones', None)
        if not bones:
            continue
        root = next((b for b in bones if b.parent is None), None)
        if root is None:
            continue
        specs.append((
            arm.name,
            _matrix_to_list(arm.matrix_basis),
            _matrix_to_list(root.matrix_local),
        ))

    _check_root_bone_orientation(specs)
    logger.info("  Root bone orientation OK (root JOBJ exports identity)")


def _matrix_to_list(m):
    return [[m[i][j] for j in range(4)] for i in range(4)]


def _check_root_bone_orientation(specs):
    """Pure helper for `_validate_root_bone_orientation`.

    `specs` is a list of `(armature_name, matrix_basis, root_matrix_local)`
    where the matrices are 4x4 row-major lists. Raises ValueError naming the
    offending rigs if any root bone would export a rotated root JOBJ.
    """
    bad = []
    for name, basis, root_local in specs:
        gc_world = _mat4_mul(_mat4_mul(_COORD_ROTATION_INV, basis), root_local)
        if not _has_identity_rotation(gc_world):
            bad.append(name)

    if not bad:
        return

    sample = ", ".join(bad[:3]) + ("…" if len(bad) > 3 else "")
    raise ValueError(
        "Root bone of %d armature(s) [%s] would export a non-identity root "
        "JOBJ rotation. The game applies the root joint's rotation as the "
        "model's base orientation and does not cancel it, so the whole "
        "model renders turned (typically 90 deg) in-game even though "
        "Blender looks correct. The root bone must be axis-aligned "
        "(pointing +Z with Roll = 0) before export. This is a manual fix — "
        "the prep scripts do not adjust root orientation.\n"
        "\n"
        "  - If the mesh and the root bone share the same orientation: in "
        "Edit mode aim the root bone straight up (+Z) and clear its roll "
        "(Armature > Bone Roll > Clear Roll).\n"
        "\n"
        "  - If the mesh and the root bone are in DIFFERENT orientations "
        "(e.g. a Z-up mesh under a Y-up root bone): you cannot just "
        "re-orient the rig, because rotating the bone also rotates the mesh "
        "skinned to it. Rotate the root bone to axis-aligned (which rotates "
        "the mesh with it), then rotate the mesh object by the INVERSE of "
        "that same rotation. The bone ends up aligned and the mesh lands "
        "back in its correct orientation.\n"
        "\n"
        "  - If the root bone is already animated, do not re-orient it in "
        "place (that rotates its children): add an axis-aligned 'Origin' "
        "bone at the rig origin and parent the current root to it.\n"
        "\n"
        "See technical-docs/exporter_setup.md > Troubleshooting > 'Model "
        "renders rotated in-game (non-identity root bone)'."
        % (len(bad), sample)
    )


# ---------------------------------------------------------------------------
# Root joint animation
# ---------------------------------------------------------------------------
#
# The root (origin) joint must stay static — the game does not treat it as
# a normal animatable joint. Depending on a per-model flag the engine
# either strips the root joint's animation outright when an animation is
# selected, or it writes the root joint transform itself every frame as
# the model's world placement (discarding whatever the animation set), or
# — in the "use root joint animation" mode — lets the root animation drive
# the model's world position so the whole model slides off the spot the
# game placed it. In every case author-supplied animation on the root bone
# does not play as authored. The sanctioned rig keeps the root a static
# wrapper and animates from its children, so this guard rejects any action
# that animates the root bone. Disassembly evidence in
# technical-docs/implementation_notes.md § Root joint animation.

# Pose-bone transform channels; the array index is a separate FCurve
# attribute, so the data path ends at the channel name.
_POSE_BONE_CHANNEL_RE = re.compile(
    r'pose\.bones\["(.+?)"\]\.'
    r'(location|rotation_euler|rotation_quaternion|rotation_axis_angle|scale)$'
)


def _action_animates_bone(action, bone_name):
    """True if `action` has a transform FCurve with 2+ keyframes on the
    named pose bone — genuine motion, not a single static pose key."""
    for fc in getattr(action, 'fcurves', ()) or ():
        m = _POSE_BONE_CHANNEL_RE.match(getattr(fc, 'data_path', '') or '')
        if m is None or m.group(1) != bone_name:
            continue
        if len(getattr(fc, 'keyframe_points', ())) >= 2:
            return True
    return False


def _validate_origin_bone_not_animated(context, logger):
    """Reject scenes whose root (origin) bone carries animation.

    See `_check_origin_bone_not_animated` for the in-game failure mode.
    Scans every action for transform keyframes on each armature's
    parent-less root bone; in the single-armature Pokémon/character case
    every pose action is exported, so a match here would ship a broken
    animation. The fix is the same canonical-parent move the
    root-orientation guard points at.
    """
    try:
        import bpy
    except ImportError:
        bpy = None
    scene = getattr(context, 'scene', None)
    objects = list(scene.objects) if scene is not None else (
        list(bpy.data.objects) if bpy is not None else []
    )
    armatures = [o for o in objects if getattr(o, 'type', None) == 'ARMATURE']
    actions = list(bpy.data.actions) if bpy is not None else []

    specs = []
    for arm in armatures:
        bones = getattr(arm.data, 'bones', None)
        if not bones:
            continue
        root = next((b for b in bones if b.parent is None), None)
        if root is None:
            continue
        offending = [a.name for a in actions
                     if _action_animates_bone(a, root.name)]
        specs.append((arm.name, root.name, offending))

    _check_origin_bone_not_animated(specs)
    logger.info("  Origin bone animation OK (root JOBJ stays static)")


def _check_origin_bone_not_animated(specs):
    """Pure helper for `_validate_origin_bone_not_animated`.

    `specs` is a list of `(armature_name, root_bone_name,
    offending_action_names)`. Raises ValueError naming each rig and the
    actions that animate its root/origin bone; a no-op when every rig's
    offending list is empty.

    Why this breaks in-game: the engine does not treat the root JOBJ as a
    normal animatable joint. A per-model flag can make it strip the root
    joint's animation when an animation is selected; otherwise the game
    writes the root joint transform itself each frame as the model's world
    placement (discarding the animation), and in the "use root joint
    animation" mode the root animation instead drives the model's world
    position — sliding the whole model off the spot the game placed it.
    Game-native models keep the root a static wrapper and animate from its
    children.
    """
    bad = [(name, root, acts) for name, root, acts in specs if acts]
    if not bad:
        return

    lines = []
    for name, root, acts in bad:
        sample = ", ".join(acts[:3]) + ("…" if len(acts) > 3 else "")
        lines.append("  - %s: root bone '%s' animated by %s"
                     % (name, root, sample))

    raise ValueError(
        "The root (origin) bone must stay static, but %d armature(s) "
        "animate it:\n%s\n"
        "\n"
        "The game does not treat the root joint as a normal animatable "
        "joint: depending on the model's flags it strips the root joint's "
        "animation outright, or it overwrites the root joint every frame "
        "with the model's world placement, or it lets the root animation "
        "drive the whole model's position so the model slides off where "
        "the game placed it. Either way the animation does not play as "
        "authored and the model looks broken in-game. Game-native models "
        "keep the root bone a static wrapper and animate from its "
        "children.\n"
        "\n"
        "Fix: add a new axis-aligned 'Origin' bone at the rig origin and "
        "parent the current (animated) root bone to it. The Origin bone "
        "becomes the static model root; the formerly-root bone becomes a "
        "normal child whose animation exports normally.\n"
        "\n"
        "See technical-docs/exporter_setup.md > Troubleshooting > 'Root "
        "motion is ignored or the model is mispositioned in-game (animated "
        "origin bone)'."
        % (len(bad), "\n".join(lines))
    )


def _validate_vertex_weight_count(context, logger):
    """Reject any vertex with more than 4 non-zero bone weights.

    The GX envelope matrix-index byte packs up to 4 MTXIDX slots, so the
    hardware cannot blend more than 4 influences per vertex. Weight
    limiting lives in both prep scripts (`prepare_for_pkx_export.py` and
    `prepare_for_dat_export.py`); this check just guards against running
    the exporter on a scene where that step was skipped.
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
            f"{MAX_VERTEX_WEIGHTS}. Run scripts/prepare_for_pkx_export.py "
            f"(PKX output) or scripts/prepare_for_dat_export.py (.dat output) "
            f"first (tune MAX_WEIGHTS_PER_VERTEX). Sample offenders: {sample}"
        )


def _validate_mesh_owner_disjoint_from_deformers(context, logger):
    """Reject scenes where a mesh's owner bone is also an envelope deformer.

    Game-native models keep mesh-owner joints (JOBJ_ENVELOPE_MODEL) strictly
    disjoint from envelope-weight targets (JOBJ_SKELETON + IBM). When the
    two overlap, `refine_bone_flags` strips SKELETON from the bone so it
    can own the mesh; the envelope coord system then resolves wrong for
    every vert weighted to it and the mesh floats / animates incorrectly
    in-game. Both prep scripts insert holder bones to enforce disjointness
    (see `reparent_meshes_to_holder_bones`); this check guards against
    running the exporter on a scene where that step was skipped or where
    the user authored a mesh that violates the invariant by hand.
    """
    try:
        import bpy
    except ImportError:
        bpy = None
    scene = getattr(context, 'scene', None)
    objects = list(scene.objects) if scene is not None else (
        list(bpy.data.objects) if bpy is not None else []
    )
    armatures = [arm for arm in objects if getattr(arm, 'type', None) == 'ARMATURE']
    meshes_by_armature = {
        arm: [obj for obj in objects
              if obj.parent is arm and getattr(obj, 'type', None) == 'MESH']
        for arm in armatures
    }
    _check_mesh_owner_disjoint(meshes_by_armature)
    logger.info("  Mesh-owner / deformer disjointness OK")


def _check_mesh_owner_disjoint(meshes_by_armature):
    offenders = []
    for arm, meshes in meshes_by_armature.items():
        arm_data = getattr(arm, 'data', None)
        if arm_data is None or not arm_data.bones:
            continue
        bone_names = {b.name for b in arm_data.bones}
        root_name = arm_data.bones[0].name
        parent_of = {b.name: (b.parent.name if b.parent else None)
                     for b in arm_data.bones}

        mesh_weighted = {m: _weighted_bones(m, bone_names) for m in meshes}
        deformers = set().union(*mesh_weighted.values()) if mesh_weighted else set()

        for m in meshes:
            owner = _mesh_owner_bone(m, mesh_weighted[m], bone_names,
                                     root_name, parent_of)
            if owner in deformers:
                offenders.append((m.name, owner))
                if len(offenders) >= 10:
                    break
        if len(offenders) >= 10:
            break

    if offenders:
        sample = "; ".join(f"{name}→{owner}" for name, owner in offenders[:5])
        raise ValueError(
            f"Mesh owner bone is also an envelope-weight deformer for "
            f"{len(offenders)} mesh(es). The game requires mesh-owner joints "
            f"(JOBJ_ENVELOPE_MODEL) to be disjoint from weighted deformer "
            f"joints (JOBJ_SKELETON) — overlapping joints render offset in "
            f"game. Run scripts/prepare_for_pkx_export.py (PKX output) or "
            f"scripts/prepare_for_dat_export.py (.dat output) first; the "
            f"holder-bone step (reparent_meshes_to_holder_bones) inserts a "
            f"non-deformer owner bone for each affected mesh. Sample "
            f"offenders (mesh→owner): {sample}"
        )


def _weighted_bones(mesh, bone_names):
    """Bones this mesh actually weights vertices to.

    In: mesh (bpy.types.Object, type='MESH'); bone_names (set[str]).
    Out: set[str] — vertex groups naming a real bone with any non-zero weight.
    """
    data = getattr(mesh, 'data', None)
    if data is None:
        return set()
    group_names = {vg.index: vg.name for vg in mesh.vertex_groups}
    return {name for v in data.vertices for g in v.groups
            if g.weight > 0.0
            for name in (group_names.get(g.group),) if name in bone_names}


def _mesh_owner_bone(mesh, weighted, bone_names, root_name, parent_of):
    """Resolve the joint this mesh will be owned by once exported.

    Mirrors the describe phase's own rule (`_determine_parent_bone_name`): an
    explicit ``parent_bone`` naming a real bone wins outright, whatever
    ``parent_type`` says — the importer bone-links meshes while leaving them
    object-parented to the armature, so requiring `parent_type == 'BONE'` here
    would resolve a different owner than the export actually writes. Only a
    mesh with no such link falls back to the nearest common ancestor of its
    weighted bones (the root when they share none).

    In: mesh (bpy.types.Object); weighted (set[str], bones the mesh weights to);
        bone_names (set[str]); root_name (str); parent_of (dict[str, str|None]).
    Out: str — owner bone name.
    """
    if getattr(mesh, 'parent_bone', None) in bone_names:
        return mesh.parent_bone
    if not weighted:
        return root_name

    common = set.intersection(*[set(_ancestors(n, parent_of)) for n in weighted])
    for name in _ancestors(next(iter(weighted)), parent_of):
        if name in common:
            return name
    return root_name


def _ancestors(name, parent_of):
    """Bone name plus every ancestor, nearest first.

    In: name (str); parent_of (dict[str, str|None]).
    Out: list[str].
    """
    chain = []
    while name is not None:
        chain.append(name)
        name = parent_of.get(name)
    return chain


def _validate_texture_sizes(context, logger):
    """Reject any texture with a dimension above MAX_TEXTURE_DIM.

    GameCube RAM and TMEM budgets can't absorb arbitrarily-large textures
    from GLB/FBX rips. Both prep scripts (`prepare_for_pkx_export.py` and
    `prepare_for_dat_export.py`) downscale images above the cap; this
    check guards against running the exporter on a scene where that step
    was skipped.
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
            f"scripts/prepare_for_pkx_export.py (PKX output) or "
            f"scripts/prepare_for_dat_export.py (.dat output) first to "
            f"downscale. Sample offenders: {sample}"
        )


# ---------------------------------------------------------------------------
# Textures per material
# ---------------------------------------------------------------------------
#
# GX exposes only 8 texture units (GX_MAX_TEXMAP). The render-time material
# setup asserts when a material activates a 9th texgen, which halts the
# console — so this is a hard hardware cap, not a fidelity concern. Arbitrary
# GLB/FBX rips can stack many image nodes on one material and trip it. The
# count is a proxy: image-texture nodes with an assigned image, per material.

def _count_material_image_textures(mat):
    """Number of image-texture nodes with an assigned image on a material."""
    if not getattr(mat, 'use_nodes', False):
        return 0
    node_tree = getattr(mat, 'node_tree', None)
    if node_tree is None:
        return 0
    return sum(1 for node in node_tree.nodes
               if getattr(node, 'bl_idname', None) == 'ShaderNodeTexImage'
               and getattr(node, 'image', None))


def _validate_material_texture_count(context, logger):
    """Reject materials that bind more than 8 image textures.

    See `_check_material_texture_count` for the failure mode. Scans every
    mesh's material slots (mirroring `_validate_texture_sizes`).
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
    specs = []
    for obj in objects:
        if getattr(obj, 'type', None) != 'MESH':
            continue
        for slot in getattr(obj, 'material_slots', []):
            mat = getattr(slot, 'material', None)
            if mat is None or id(mat) in seen:
                continue
            seen.add(id(mat))
            specs.append((mat.name, _count_material_image_textures(mat)))

    _check_material_texture_count(specs)
    logger.info("  Material texture count OK (<= %d per material)",
                MAX_TEXTURES_PER_MATERIAL)


def _check_material_texture_count(specs):
    """Pure helper for `_validate_material_texture_count`.

    `specs` is a list of `(material_name, image_texture_count)`. Raises
    ValueError naming the offenders if any material exceeds the GX texmap
    cap; a no-op otherwise.

    Why this breaks in-game: GX has 8 texture units per material. The
    engine's material setup asserts (and halts the console) when a material
    binds a 9th texture — a hard crash, not a silent misrender.
    """
    bad = [(name, count) for name, count in specs
           if count > MAX_TEXTURES_PER_MATERIAL]
    if not bad:
        return

    sample = "; ".join("%s (%d)" % (name, count) for name, count in bad[:5])
    raise ValueError(
        "%d material(s) bind more than %d image textures [%s]. The GameCube "
        "GX hardware has only %d texture units per material and the game "
        "asserts and freezes when a material activates a 9th. Reduce the "
        "image textures on each listed material — bake or merge texture "
        "layers, or split the mesh so each material stays within the limit."
        % (len(bad), MAX_TEXTURES_PER_MATERIAL, sample, MAX_TEXTURES_PER_MATERIAL)
    )


# ---------------------------------------------------------------------------
# Animation timing (PKX)
# ---------------------------------------------------------------------------
#
# The battle state machine reads each PKX anim slot's primary timing to pace
# state transitions. A slot that references a real action but stores
# timing_1 = 0 triggers a divide-by-zero modulo that advances through entry
# states without pausing, reliably crashing on send-out. Unassigned / padding
# slots are exempt — the game never reads their timing. Only relevant when
# emitting a PKX (a raw .dat carries no animation header).

def _collect_zero_timing_slots(arm):
    """Labels of *assigned* PKX anim slots whose `timing_1` is zero.

    A slot is assigned when one of its sub-anim refs names a real action
    (a non-empty string), matching describe's `has_anim` test. Duck-typed
    on ``arm.get`` (a plain dict works) so it is unit-testable without bpy.
    """
    offending = []
    anim_count = int(arm.get("dat_pkx_anim_count", 17))
    for i in range(anim_count):
        prefix = "dat_pkx_anim_%02d" % i
        sub_count = int(arm.get(prefix + "_sub_count", 1))
        assigned_name = None
        for s in range(min(sub_count, 3)):
            name = arm.get(prefix + "_sub_%d_anim" % s, "")
            if isinstance(name, str) and name:
                assigned_name = name
                break
        if assigned_name is None:
            continue  # unassigned / padding slot — the game skips its timing
        timing_1 = arm.get(prefix + "_timing_1", 0.0)
        try:
            is_zero = abs(float(timing_1)) < 1e-9
        except (TypeError, ValueError):
            is_zero = True
        if is_zero:
            offending.append("slot %02d (%s)" % (i, assigned_name))
    return offending


def _validate_animation_timing(context, ext, fsys_inner_kind, logger):
    """Reject PKX exports whose assigned anim slots have `timing_1` == 0.

    See `_check_animation_timing`. PKX-scoped (mirrors
    `_validate_pkx_metadata`): a raw .dat has no anim header, so the crash
    cannot occur there.
    """
    needs_pkx = (ext == 'pkx') or (ext == 'fsys' and fsys_inner_kind == MODEL_TYPE_PKX)
    if not needs_pkx:
        return

    try:
        import bpy
    except ImportError:
        bpy = None
    scene = getattr(context, 'scene', None)
    objects = list(scene.objects) if scene is not None else (
        list(bpy.data.objects) if bpy is not None else []
    )
    armatures = [o for o in objects if getattr(o, 'type', None) == 'ARMATURE'
                 and o.get('dat_pkx_format') in ('XD', 'COLOSSEUM')]

    specs = [(arm.name, _collect_zero_timing_slots(arm)) for arm in armatures]
    _check_animation_timing(specs)
    logger.info("  Animation timing OK (assigned slots carry non-zero timing)")


def _check_animation_timing(specs):
    """Pure helper for `_validate_animation_timing`.

    `specs` is a list of `(armature_name, offending_slot_labels)`. Raises
    ValueError naming each rig and its zero-timing assigned slots; a no-op
    when every list is empty.

    Why this breaks in-game: the battle state machine divides by a slot's
    primary timing to pace its state transitions, so an assigned slot with
    timing_1 = 0 is a divide-by-zero that reliably crashes on send-out.
    """
    bad = [(name, slots) for name, slots in specs if slots]
    if not bad:
        return

    lines = []
    for name, slots in bad:
        sample = ", ".join(slots[:4]) + ("…" if len(slots) > 4 else "")
        lines.append("  - %s: %s" % (name, sample))

    raise ValueError(
        "%d armature(s) have assigned animation slots with a zero primary "
        "timing (timing_1 = 0):\n%s\n"
        "\n"
        "A PKX animation slot that references a real action but stores a "
        "zero primary timing triggers a divide-by-zero in the battle state "
        "machine and reliably crashes the game on send-out. Every assigned "
        "slot needs a non-zero timing_1. (Empty / padding slots are fine.)\n"
        "\n"
        "Fix: run scripts/prepare_for_pkx_export.py — its derive_timing step "
        "fills per-slot timings from the action durations — or set the "
        "'dat_pkx_anim_NN_timing_1' custom property on the armature to a "
        "non-zero value for each listed slot.\n"
        "\n"
        "See technical-docs/exporter_setup.md > Troubleshooting > 'Game "
        "crashes on send-out (zero animation timing)'."
        % (len(bad), "\n".join(lines))
    )


