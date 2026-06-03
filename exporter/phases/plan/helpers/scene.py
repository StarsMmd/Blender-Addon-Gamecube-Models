"""Scene-level plan helpers — refine bone flags from mesh attachment.

Pure — no bpy. Mutates IRBone.flags / inverse_bind_matrix / is_hidden in
place after the per-bone and per-mesh IR are assembled, when the bones'
geometric role (deformation target, mesh owner, ancestor of mesh, etc.)
becomes derivable.
"""
try:
    from .....shared.IR.enums import SkinType
    from .....shared.Constants.hsd import (
        JOBJ_SKELETON, JOBJ_SKELETON_ROOT, JOBJ_ENVELOPE_MODEL,
        JOBJ_LIGHTING, JOBJ_OPA, JOBJ_TEXEDGE,
        JOBJ_ROOT_OPA, JOBJ_ROOT_TEXEDGE, JOBJ_HIDDEN,
    )
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.enums import SkinType
    from shared.Constants.hsd import (
        JOBJ_SKELETON, JOBJ_SKELETON_ROOT, JOBJ_ENVELOPE_MODEL,
        JOBJ_LIGHTING, JOBJ_OPA, JOBJ_TEXEDGE,
        JOBJ_ROOT_OPA, JOBJ_ROOT_TEXEDGE, JOBJ_HIDDEN,
    )
    from shared.helpers.logger import StubLogger


def refine_bone_flags(bones, meshes, logger=StubLogger()):
    """Set bone flags based on mesh attachment and hierarchy position.

    Flag rules (matching HSD conventions):
        SKELETON_ROOT   — root bone of the armature
        SKELETON        — bones with inverse_bind_matrix (deformation bones)
        ENVELOPE_MODEL  — bones that own envelope-weighted meshes
        LIGHTING        — bones that own any mesh
        OPA             — bones that own a mesh (every mesh ships opaque)
        HIDDEN          — already set during armature describe from edit_bone.hide
        ROOT_OPA        — propagated to every ancestor of a mesh-owning bone
                          so the runtime's render dispatcher descends into the
                          subtree during pass 0.
        (none) / 0x0    — leaf bones with no mesh attachment and no deformation role
    """
    bones_with_meshes = set()
    bones_with_envelope = set()
    bones_with_texedge = set()
    bones_with_opa = set()
    for ir_mesh in meshes:
        bone_idx = ir_mesh.parent_bone_index
        if bone_idx < len(bones):
            bones_with_meshes.add(bone_idx)
            bw = ir_mesh.bone_weights
            if bw and bw.type == SkinType.WEIGHTED:
                bones_with_envelope.add(bone_idx)
            mat = ir_mesh.material
            if mat is not None and getattr(mat, 'is_translucent', False):
                bones_with_texedge.add(bone_idx)
            else:
                bones_with_opa.add(bone_idx)

    bone_name_to_idx = {b.name: i for i, b in enumerate(bones)}
    deformation_bones = set()
    for ir_mesh in meshes:
        bw = ir_mesh.bone_weights
        if bw and bw.bone_name:
            idx = bone_name_to_idx.get(bw.bone_name)
            if idx is not None:
                deformation_bones.add(idx)
        if bw and bw.assignments:
            for _, weight_list in bw.assignments:
                for bone_name, _ in weight_list:
                    idx = bone_name_to_idx.get(bone_name)
                    if idx is not None:
                        deformation_bones.add(idx)

    opa_descendant = set(bones_with_opa)
    texedge_descendant = set(bones_with_texedge)
    for i in range(len(bones) - 1, -1, -1):
        pi = bones[i].parent_index
        if pi is not None:
            if i in opa_descendant: opa_descendant.add(pi)
            if i in texedge_descendant: texedge_descendant.add(pi)

    for i, bone in enumerate(bones):
        flags = 0

        if bone.parent_index is None:
            flags |= JOBJ_SKELETON_ROOT
        if i in deformation_bones:
            flags |= JOBJ_SKELETON

        if i in bones_with_meshes:
            flags |= JOBJ_LIGHTING
            if i in bones_with_opa:
                flags |= JOBJ_OPA
            if i in bones_with_texedge:
                flags |= JOBJ_TEXEDGE
            if i in bones_with_envelope:
                flags |= JOBJ_ENVELOPE_MODEL

        if i in opa_descendant:
            flags |= JOBJ_ROOT_OPA
        if i in texedge_descendant:
            flags |= JOBJ_ROOT_TEXEDGE

        if bone.is_hidden:
            flags |= JOBJ_HIDDEN
        elif i in bones_with_meshes:
            all_hidden = all(meshes[mi].is_hidden for mi in bone.mesh_indices)
            if all_hidden:
                flags |= JOBJ_HIDDEN
                bone.is_hidden = True

        # SKEL and the mesh-owner flags are mutually exclusive in the
        # game's format: mesh-carrying bones use ENV_MODEL / HIDDEN with
        # LIGHTING|OPA; they never also carry SKEL even when they happen
        # to be deformation targets.
        if i in bones_with_meshes:
            flags &= ~JOBJ_SKELETON

        bone.flags = flags

        if i not in deformation_bones:
            bone.inverse_bind_matrix = None

    logger.debug("  Refined bone flags for %d bones (%d with meshes, %d deformation, %d envelope)",
                 len(bones), len(bones_with_meshes), len(deformation_bones), len(bones_with_envelope))
