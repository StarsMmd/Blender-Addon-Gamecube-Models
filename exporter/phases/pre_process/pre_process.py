"""Pre-process phase: validate export conditions before running the pipeline.

Checks that the output path is valid and the Blender scene is suitable
for export. Raises ValueError if any check fails, cancelling the export.
"""
import os

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
    _validate_scene(context, logger)
    _validate_baked_transforms(context, logger)
    _validate_root_bone_orientation(context, logger)
    _validate_vertex_weight_count(context, logger)
    _validate_mesh_owner_disjoint_from_deformers(context, logger)
    _validate_texture_sizes(context, logger)
    _validate_pkx_metadata(context, ext, fsys_inner_kind, logger)

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

    Both prep scripts normalise the root bone (`normalize_root_orientation`);
    this guards against exporting a scene that skipped that step — the
    in-game symptom is the whole model rendered turned 90 deg.
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
        "model's base orientation without cancelling it, so the whole model "
        "renders turned (typically 90 deg) in-game even though Blender looks "
        "correct. Fix by running scripts/prepare_for_pkx_export.py (PKX "
        "output) or scripts/prepare_for_dat_export.py (bare .dat output) "
        "against this .blend — both normalise the root bone so the exported "
        "root joint is identity." % (len(bad), sample)
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

        def ancestors(name):
            chain = []
            while name is not None:
                chain.append(name)
                name = parent_of.get(name)
            return chain

        deformers = set()
        mesh_weighted = {}
        for m in meshes:
            data = getattr(m, 'data', None)
            if data is None:
                continue
            idx_to_name = {vg.index: vg.name for vg in m.vertex_groups}
            weighted = set()
            for v in data.vertices:
                for g in v.groups:
                    if g.weight > 0.0:
                        nm = idx_to_name.get(g.group)
                        if nm in bone_names:
                            weighted.add(nm)
            mesh_weighted[m] = weighted
            deformers |= weighted

        for m in meshes:
            if getattr(m, 'parent_type', None) == 'BONE' \
                    and getattr(m, 'parent_bone', None) in bone_names:
                owner = m.parent_bone
            else:
                weighted = mesh_weighted.get(m, set())
                if not weighted:
                    owner = root_name
                else:
                    chains = [set(ancestors(n)) for n in weighted]
                    common = set.intersection(*chains)
                    if not common:
                        owner = root_name
                    else:
                        owner = root_name
                        for n in ancestors(next(iter(weighted))):
                            if n in common:
                                owner = n
                                break
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


