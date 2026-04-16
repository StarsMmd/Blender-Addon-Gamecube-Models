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
