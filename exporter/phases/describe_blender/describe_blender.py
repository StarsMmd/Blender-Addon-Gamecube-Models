"""Phase 1 (Export): Read Blender scene into an IRScene.

Reads armatures and their child meshes from the Blender scene and
produces an IRScene suitable for composition into node trees.

Works with arbitrary Blender models — no assumptions about naming
conventions or import-specific metadata.

Also extracts shiny filter parameters from armature custom properties
if present, for writing back into PKX headers during packaging.
"""
import bpy

try:
    from ....shared.IR import IRScene, IRModel
    from ....shared.IR.animation import IRBoneAnimationSet
    from ....shared.IR.enums import SkinType
    from ....shared.Constants.hsd import (
        JOBJ_SKELETON, JOBJ_SKELETON_ROOT, JOBJ_ENVELOPE_MODEL,
        JOBJ_LIGHTING, JOBJ_OPA, JOBJ_ROOT_OPA, JOBJ_HIDDEN,
    )
    from ....shared.helpers.logger import StubLogger
    from .helpers.skeleton import describe_skeleton
    from .helpers.meshes import describe_meshes
except (ImportError, SystemError):
    from shared.IR import IRScene, IRModel
    from shared.IR.animation import IRBoneAnimationSet
    from shared.IR.enums import SkinType
    from shared.Constants.hsd import (
        JOBJ_SKELETON, JOBJ_SKELETON_ROOT, JOBJ_ENVELOPE_MODEL,
        JOBJ_LIGHTING, JOBJ_OPA, JOBJ_ROOT_OPA, JOBJ_HIDDEN,
    )
    from shared.helpers.logger import StubLogger
    from exporter.phases.describe_blender.helpers.skeleton import describe_skeleton
    from exporter.phases.describe_blender.helpers.meshes import describe_meshes


def describe_blender_scene(context, options=None, logger=StubLogger()):
    """Read the active Blender scene and produce an IRScene.

    Exports all currently selected armatures. Each armature becomes one
    IRModel. Meshes parented to a selected armature are automatically
    included. Meshes not parented to any selected armature are ignored.

    Args:
        context: Blender context with active scene.
        options: dict of exporter options.
        logger: Logger instance.

    Returns:
        (IRScene, ShinyParams | None) — the scene description and optional
        shiny filter parameters (or None if no shiny data found).
    """
    if options is None:
        options = {}

    logger.info("=== Export Phase 1: Describe Blender Scene ===")

    # Collect selected armatures
    armatures = [
        obj for obj in context.selected_objects
        if obj.type == 'ARMATURE'
    ]

    if not armatures:
        raise ValueError(
            "No armatures selected. Select the armature(s) you want to export."
        )

    models = []
    for armature in armatures:
        logger.info("  Processing armature '%s'", armature.name)

        bones = describe_skeleton(armature, logger=logger)
        meshes = describe_meshes(armature, bones, logger=logger)

        # Populate mesh_indices on bones
        for mesh_idx, ir_mesh in enumerate(meshes):
            bone_idx = ir_mesh.parent_bone_index
            if bone_idx < len(bones):
                bones[bone_idx].mesh_indices.append(mesh_idx)

        # Refine bone flags now that we know which bones own meshes
        _refine_bone_flags(bones, meshes, logger)

        bones_with_meshes = sum(1 for b in bones if b.mesh_indices)
        logger.info("  Mesh attachment: %d mesh(es) across %d bone(s)", len(meshes), bones_with_meshes)
        for b in bones:
            if b.mesh_indices:
                logger.debug("    bone '%s': mesh_indices=%s flags=%#x", b.name, b.mesh_indices, b.flags)

        # Count animation sets from Blender actions associated with this armature
        bone_animations = _count_animation_sets(armature, logger)

        model = IRModel(
            name=armature.name,
            bones=bones,
            meshes=meshes,
            bone_animations=bone_animations,
        )
        models.append(model)

    ir_scene = IRScene(models=models, lights=[])

    # Extract shiny filter parameters from the first armature that has them
    shiny_params = _extract_shiny_params(armatures, logger)

    logger.info("=== Export Phase 1 complete: %d model(s), %d light(s), shiny=%s ===",
                len(ir_scene.models), len(ir_scene.lights), shiny_params is not None)
    return ir_scene, shiny_params


def _count_animation_sets(armature, logger):
    """Count animation actions associated with an armature.

    Creates one empty IRBoneAnimationSet per action found. The compose
    phase uses these as slots to generate placeholder animations,
    ensuring the exported model has the same number of animation sets
    as the original.

    Args:
        armature: Blender armature object.
        logger: Logger instance.

    Returns:
        list[IRBoneAnimationSet] — one per action found.
    """
    # Find actions that target this armature's bones
    # Actions with use_fake_user=True persist even when not active
    armature_name = armature.name.split('_skeleton_')[0] if '_skeleton_' in armature.name else armature.name
    actions = []
    for action in bpy.data.actions:
        # Match by name prefix (importer names actions as "{model}_Anim_NN")
        # or by having fcurves that target pose bones
        if action.name.startswith(armature_name + '_'):
            actions.append(action)
        elif action.id_root == 'OBJECT':
            # Check if any fcurve targets a bone in this armature
            for fc in action.fcurves:
                if fc.data_path.startswith('pose.bones['):
                    actions.append(action)
                    break

    anim_sets = []
    for action in actions:
        anim_set = IRBoneAnimationSet(
            name=action.name,
            tracks=[],
            loop=False,
        )
        anim_sets.append(anim_set)

    if anim_sets:
        logger.info("  Found %d animation action(s) for armature '%s'", len(anim_sets), armature.name)

    return anim_sets


def _refine_bone_flags(bones, meshes, logger):
    """Set bone flags based on mesh attachment and hierarchy position.

    Called after both bones and meshes are described, so we know which
    bones own geometry and what kind of skinning they use.

    Flag rules (matching HSD conventions):
        SKELETON_ROOT   — root bone of the armature
        SKELETON        — bones with inverse_bind_matrix (deformation bones)
        ENVELOPE_MODEL  — bones that own envelope-weighted meshes
        LIGHTING        — bones that own any mesh (mesh rendering uses lighting)
        OPA             — bones that own opaque meshes
        HIDDEN          — already set during skeleton describe from edit_bone.hide
        ROOT_OPA        — root-level bones in a chain that contains opaque meshes
        (none) / 0x0    — leaf bones with no mesh attachment and no deformation role
    """
    # Determine which bones own meshes and what kind
    bones_with_meshes = set()
    bones_with_envelope = set()
    for ir_mesh in meshes:
        bone_idx = ir_mesh.parent_bone_index
        if bone_idx < len(bones):
            bones_with_meshes.add(bone_idx)
            bw = ir_mesh.bone_weights
            if bw and bw.type == SkinType.WEIGHTED:
                bones_with_envelope.add(bone_idx)

    # Collect deformation bones: bones referenced by OTHER bones' meshes
    # as skinning targets. A bone holding its own mesh (self-referencing
    # SINGLE_BONE) is not a deformation bone — it's a mesh container.
    bone_name_to_idx = {b.name: i for i, b in enumerate(bones)}
    deformation_bones = set()
    for ir_mesh in meshes:
        bw = ir_mesh.bone_weights
        parent = ir_mesh.parent_bone_index
        if bw and bw.bone_name:
            idx = bone_name_to_idx.get(bw.bone_name)
            if idx is not None and idx != parent:
                deformation_bones.add(idx)
        if bw and bw.assignments:
            for _, weight_list in bw.assignments:
                for bone_name, _ in weight_list:
                    idx = bone_name_to_idx.get(bone_name)
                    if idx is not None and idx != parent:
                        deformation_bones.add(idx)

    # Find which bones are at the root of a subtree containing meshes
    has_mesh_descendant = set()
    # Walk bottom-up: if a bone has meshes or a child with meshes, mark it
    for i in range(len(bones) - 1, -1, -1):
        if i in bones_with_meshes:
            has_mesh_descendant.add(i)
        if i in has_mesh_descendant and bones[i].parent_index is not None:
            has_mesh_descendant.add(bones[i].parent_index)

    for i, bone in enumerate(bones):
        flags = 0

        # Root bone
        if bone.parent_index is None:
            flags |= JOBJ_SKELETON_ROOT

        # Skeleton deformation bone
        if i in deformation_bones:
            flags |= JOBJ_SKELETON

        # Bone owns mesh(es)
        if i in bones_with_meshes:
            flags |= JOBJ_LIGHTING | JOBJ_OPA
            if i in bones_with_envelope:
                flags |= JOBJ_ENVELOPE_MODEL

        # Root-level OPA: root bone or skeleton root with mesh descendants
        if bone.parent_index is None and i in has_mesh_descendant:
            flags |= JOBJ_ROOT_OPA
        # Also set ROOT_OPA on skeleton bones that are the root of a mesh chain
        if i in deformation_bones and bone.parent_index is not None:
            parent = bones[bone.parent_index]
            if parent.parent_index is None:
                flags |= JOBJ_ROOT_OPA

        # HIDDEN: set if the bone is hidden in Blender (edit_bone.hide),
        # OR if all meshes on this bone are hidden (hide_render=True)
        if bone.is_hidden:
            flags |= JOBJ_HIDDEN
        elif i in bones_with_meshes:
            all_hidden = all(meshes[mi].is_hidden for mi in bone.mesh_indices)
            if all_hidden:
                flags |= JOBJ_HIDDEN
                bone.is_hidden = True

        bone.flags = flags

    logger.debug("  Refined bone flags for %d bones (%d with meshes, %d deformation, %d envelope)",
                 len(bones), len(bones_with_meshes), len(deformation_bones), len(bones_with_envelope))


def _extract_shiny_params(armatures, logger):
    """Find and extract shiny filter custom properties from armatures.

    Scans the given armatures for the dat_shiny_* registered properties
    set during import. Returns the first set found, or None.

    Args:
        armatures: list of Blender armature objects.
        logger: Logger instance.

    Returns:
        ShinyParams, or None.
    """
    # TODO: Implement — scan armatures for dat_shiny_route_r, dat_shiny_brightness_r, etc.
    return None
