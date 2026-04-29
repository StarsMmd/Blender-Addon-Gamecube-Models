"""Describe Joint→Mesh→PObject chains as IRMesh dataclasses.

Extracts geometry (vertices, faces, UVs, colors, normals) and bone weight
classification from parsed PObject nodes without any bpy calls.
"""
try:
    from .....shared.helpers.math_shim import Matrix, Vector
    from .....shared.IR.geometry import IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights, IRShapeKey
    from .....shared.IR.enums import SkinType
    from .....shared.Constants.hsd import (
        POBJ_TYPE_MASK, POBJ_SKIN, POBJ_ENVELOPE, POBJ_SHAPEANIM,
        POBJ_CULLFRONT, POBJ_CULLBACK,
        JOBJ_SKELETON, JOBJ_SKELETON_ROOT, JOBJ_HIDDEN,
    )
    from .....shared.Constants.gx import (
        GX_VA_POS, GX_VA_NRM, GX_VA_NBT, GX_VA_CLR0, GX_VA_CLR1,
        GX_VA_TEX0, GX_VA_PNMTXIDX,
    )
    from .....shared.helpers.logger import StubLogger
    from .....shared.helpers.scale import GC_TO_METERS
except (ImportError, SystemError):
    from shared.helpers.math_shim import Matrix, Vector
    from shared.IR.geometry import IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights, IRShapeKey
    from shared.IR.enums import SkinType
    from shared.Constants.hsd import (
        POBJ_TYPE_MASK, POBJ_SKIN, POBJ_ENVELOPE, POBJ_SHAPEANIM,
        POBJ_CULLFRONT, POBJ_CULLBACK,
        JOBJ_SKELETON, JOBJ_SKELETON_ROOT, JOBJ_HIDDEN,
    )
    from shared.Constants.gx import (
        GX_VA_POS, GX_VA_NRM, GX_VA_NBT, GX_VA_CLR0, GX_VA_CLR1,
        GX_VA_TEX0, GX_VA_PNMTXIDX,
    )
    from shared.helpers.logger import StubLogger
    from shared.helpers.scale import GC_TO_METERS


def describe_meshes(root_joint, bones, joint_to_bone_index, image_cache=None, logger=StubLogger(), options=None):
    """Walk a Joint tree and extract geometry from Mesh→PObject chains as IRMeshes.

    In: root_joint (Joint, parsed); bones (list[IRBone], mutated to add mesh_indices); joint_to_bone_index (dict[int,int]); image_cache (dict|None); logger (Logger); options (dict|None).
    Out: list[IRMesh] in tree-walk order, vertices in meters, world-space for rigid/single-bone weights.
    """
    if image_cache is None:
        image_cache = {}
    if options is None:
        options = {}
    meshes = []
    material_cache = {}  # {mobject.address: IRMaterial} — dedup shared materials

    _walk_joints(
        root_joint, bones, joint_to_bone_index, options, image_cache, logger,
        meshes, material_cache,
    )

    # Pad numeric mesh names based on total count
    if meshes:
        digits = len(str(len(meshes) - 1))
        for mesh in meshes:
            if mesh.name.isdigit():
                mesh.name = mesh.name.zfill(digits)

    return meshes


def _walk_joints(joint, bones, joint_to_bone_index, options, image_cache, logger,
                 meshes, material_cache):
    """Walk the Joint tree, dispatching Mesh chains to _walk_mesh_chain.

    In: joint (Joint, recursed); bones (list[IRBone]); joint_to_bone_index (dict[int,int]); options (dict); image_cache (dict); logger (Logger); meshes (list[IRMesh], appended in place); material_cache (dict[int, IRMaterial]).
    Out: None — mutates `meshes` and `bones[*].mesh_indices`.
    """
    bone_index = joint_to_bone_index.get(joint.address, 0)

    if joint.property is not None and hasattr(joint.property, 'pobject'):
        _walk_mesh_chain(
            joint.property, joint, bone_index,
            bones, joint_to_bone_index, options, image_cache, logger,
            meshes, material_cache,
        )

    if joint.child and not (joint.flags & (1 << 12)):  # JOBJ_INSTANCE
        _walk_joints(joint.child, bones, joint_to_bone_index, options,
                     image_cache, logger, meshes, material_cache)
    if joint.next:
        _walk_joints(joint.next, bones, joint_to_bone_index, options,
                     image_cache, logger, meshes, material_cache)


def _walk_mesh_chain(mesh_node, joint, bone_index,
                     bones, joint_to_bone_index, options, image_cache, logger,
                     meshes, material_cache):
    """Walk a Mesh (DObject) linked list, appending one IRMesh per PObj.

    In: mesh_node (Mesh, head of list); joint (Joint, owning); bone_index (int, ≥0); bones (list[IRBone]); joint_to_bone_index (dict[int,int]); options (dict); image_cache (dict); logger (Logger); meshes (list[IRMesh], appended); material_cache (dict[int,IRMaterial]).
    Out: None — mutates `meshes`, `bones[*].mesh_indices`, and `material_cache`.
    """
    while mesh_node:
        ir_material = _resolve_material(mesh_node, material_cache, image_cache, options, logger)

        pobj = mesh_node.pobject
        while pobj:
            ir_mesh = _describe_pobj(
                pobj, joint, bone_index, len(meshes),
                bones, joint_to_bone_index, options, image_cache, logger,
                ir_material=ir_material,
            )
            if ir_mesh is not None:
                bones[bone_index].mesh_indices.append(len(meshes))
                meshes.append(ir_mesh)
            pobj = pobj.next
        mesh_node = mesh_node.next


def _resolve_material(mesh_node, material_cache, image_cache, options, logger):
    """Return an IRMaterial for a Mesh (DObject), describing once and caching by mobject address.

    In: mesh_node (Mesh, parsed); material_cache (dict[int,IRMaterial], updated on miss); image_cache (dict); options (dict); logger (Logger).
    Out: IRMaterial|None — None when mesh_node.mobject is None.
    """
    if mesh_node.mobject is None:
        return None

    mob_addr = mesh_node.mobject.address
    cached = material_cache.get(mob_addr)
    if cached is not None:
        logger.debug("    reusing cached IRMaterial for DObj 0x%X (mob 0x%X)", mesh_node.address, mob_addr)
        return cached

    try:
        from .materials import describe_material
    except (ImportError, SystemError):
        from importer.phases.describe.helpers.materials import describe_material
    ir_material = describe_material(mesh_node.mobject, image_cache=image_cache, logger=logger, options=options)
    material_cache[mob_addr] = ir_material
    return ir_material


def _describe_pobj(pobj, joint, bone_index, count,
                   bones, joint_to_bone_index, options, image_cache, logger,
                   ir_material=None):
    """Orchestrate geometry extraction for one PObject into an IRMesh.

    In: pobj (PObject, parsed); joint (Joint, owning); bone_index (int, ≥0); count (int, mesh-naming counter); bones (list[IRBone]); joint_to_bone_index (dict[int,int]); options (dict); image_cache (dict); logger (Logger); ir_material (IRMaterial|None).
    Out: IRMesh|None — None if PObj has no position attribute.
    """
    pos_idx = pobj.find_attribute_index(GX_VA_POS)
    if pos_idx is None:
        return None

    face_lists_copy, faces = _validated_face_lists(pobj, pos_idx, count, logger, options)
    verts_out = [tuple(c * GC_TO_METERS for c in v) for v in pobj.sources[pos_idx]]

    uv_layers, color_layers, normals = _collect_attribute_layers(pobj, face_lists_copy, faces)
    color_layers = _fabricate_missing_color_layers(color_layers, faces, options, pobj.address, logger)

    bone_weights = _extract_bone_weights(
        pobj, joint, bone_index, bones, joint_to_bone_index, faces,
        verts_out, normals, face_lists_copy, logger, options
    )

    if bone_weights and bone_weights.type in (SkinType.RIGID, SkinType.SINGLE_BONE):
        verts_out = _world_transform_vertices(verts_out, bones[bone_index].world_matrix)

    return IRMesh(
        name=pobj.name if pobj.name else str(count),
        vertices=verts_out,
        faces=faces,
        uv_layers=uv_layers,
        color_layers=color_layers,
        normals=normals,
        material=ir_material,
        bone_weights=bone_weights,
        is_hidden=bool(joint.flags & JOBJ_HIDDEN),
        parent_bone_index=bone_index,
        cull_front=bool(pobj.flags & POBJ_CULLFRONT),
        cull_back=bool(pobj.flags & POBJ_CULLBACK),
    )


def _validated_face_lists(pobj, pos_idx, count, logger, options):
    """Return per-attribute face_lists and position faces, dropping degenerate triangles.

    In: pobj (PObject, parsed); pos_idx (int, ≥0, position attribute index); count (int, mesh number for the warning); logger (Logger); options (dict|None).
    Out: tuple (face_lists: list[list[list[int]]], faces: list[list[int]]) — both pruned of degenerate entries.
    """
    face_lists_copy = [list(fl) for fl in pobj.face_lists]
    faces = list(pobj.face_lists[pos_idx])
    orig_face_count = len(faces)
    face_lists_copy, faces = _validate_mesh(face_lists_copy, faces)
    if len(faces) != orig_face_count:
        logger.leniency("degenerate_faces_pruned",
                        "PObj 0x%X mesh#%d: removed %d degenerate faces (%d → %d); game would render garbage",
                        pobj.address, count, orig_face_count - len(faces), orig_face_count, len(faces))
    return face_lists_copy, faces


def _collect_attribute_layers(pobj, face_lists_copy, faces):
    """Collect UV / color / normal layers from a PObject's vertex attributes.

    In: pobj (PObject, parsed); face_lists_copy (list[list[list[int]]], one per attribute); faces (list[list[int]], position faces).
    Out: tuple (uv_layers: list[IRUVLayer], color_layers: list[IRColorLayer], normals: list[tuple]|None).
    """
    uv_layers = []
    color_layers = []
    normals = None
    for i, vertex in enumerate(pobj.vertex_list.vertices):
        if vertex.isTexture():
            tex_idx = vertex.attribute - GX_VA_TEX0
            uv_layers.append(_extract_uv_layer(pobj.sources[i], face_lists_copy[i], faces, tex_idx))
        elif vertex.attribute in (GX_VA_NRM, GX_VA_NBT):
            normals = _extract_normals(pobj.sources[i], face_lists_copy[i], faces,
                                       is_nbt=(vertex.attribute == GX_VA_NBT))
        elif vertex.attribute in (GX_VA_CLR0, GX_VA_CLR1):
            color_num = '0' if vertex.attribute == GX_VA_CLR0 else '1'
            cl, al = _extract_color_layers(pobj.sources[i], face_lists_copy[i], faces, color_num)
            color_layers.append(cl)
            color_layers.append(al)
    return uv_layers, color_layers, normals


def _fabricate_missing_color_layers(color_layers, faces, options, pobj_addr, logger):
    """Append default white color_0/alpha_0 layers when missing.

    In: color_layers (list[IRColorLayer], not mutated); faces (list[list[int]]); options (dict|None, unused — kept for signature stability); pobj_addr (int, for the leniency report); logger (Logger).
    Out: list[IRColorLayer] — original layers plus any fabricated white layers.
    """
    has_color_0 = any(cl.name == 'color_0' for cl in color_layers)
    has_alpha_0 = any(cl.name == 'alpha_0' for cl in color_layers)
    if has_color_0 and has_alpha_0:
        return list(color_layers)

    total_loops = sum(len(f) for f in faces)
    logger.leniency("missing_vertex_colors",
                    "PObj 0x%X missing CLR0 %s%s; fabricating white (game would render unlit)",
                    pobj_addr,
                    "color" if not has_color_0 else "",
                    "+alpha" if (not has_color_0 and not has_alpha_0) else ("alpha" if not has_alpha_0 else ""))

    out = list(color_layers)
    if not has_color_0:
        out.append(IRColorLayer(name='color_0', colors=[(1.0, 1.0, 1.0, 1.0)] * total_loops))
    if not has_alpha_0:
        out.append(IRColorLayer(name='alpha_0', colors=[(1.0, 1.0, 1.0, 1.0)] * total_loops))
    return out


def _world_transform_vertices(vertices, world_matrix):
    """Transform a vertex list from local space to world space by `world_matrix`.

    In: vertices (list[tuple[float,float,float]], in meters); world_matrix (4×4 list[list[float]]).
    Out: list[tuple[float,float,float]] — new list, same length, in world space.
    """
    parent_world = Matrix(world_matrix)
    return [tuple(parent_world @ Vector(v)) for v in vertices]


def _validate_mesh(face_lists, faces):
    """Remove faces with repeated vertices (degenerate tri-strip artifacts).

    In: face_lists (list[list[list[int]]], one per attribute, each a list of faces); faces (list[list[int]], position face list).
    Out: tuple (pruned_face_lists, pruned_faces) with degenerate entries dropped in lockstep.
    """
    pruned_faces = []
    pruned_face_lists = [[] for _ in range(len(face_lists))]
    for face_id, face in enumerate(faces):
        if len(face) == len(set(face)):
            pruned_faces.append(face)
            for i in range(len(face_lists)):
                if face_id < len(face_lists[i]):
                    pruned_face_lists[i].append(face_lists[i][face_id])
    return pruned_face_lists, pruned_faces


def _extract_uv_layer(source, face_list, faces, tex_index):
    """Extract per-loop UV coordinates with V-flip into an IRUVLayer.

    In: source (sequence of (u,v) pairs, the UV source); face_list (list[list[int]], UV attr face indices); faces (list[list[int]], position faces, defines loop order); tex_index (int, ≥0, layer name suffix).
    Out: IRUVLayer with .uvs in standard bottom-left origin.
    """
    uvs = []
    for face_id, face in enumerate(faces):
        uv_face = face_list[face_id] if face_id < len(face_list) else face
        for vert_idx_in_face in range(len(face)):
            src_idx = uv_face[vert_idx_in_face]
            coords = source[src_idx]
            uvs.append((coords[0], 1.0 - coords[1]))
    return IRUVLayer(name=f'uvtex_{tex_index}', uvs=uvs)


def _extract_normals(source, face_list, faces, is_nbt=False):
    """Extract per-loop normals as unit-length 3-tuples.

    In: source (sequence of normal vectors or NBT triples); face_list (list[list[int]]); faces (list[list[int]]); is_nbt (bool, True drops binormal/tangent).
    Out: list[tuple[float,float,float]], one per loop, normalized.
    """
    normals = []
    for face_id, face in enumerate(faces):
        attr_face = face_list[face_id] if face_id < len(face_list) else face
        for vert_idx_in_face in range(len(face)):
            src_idx = attr_face[vert_idx_in_face]
            n = source[src_idx]
            if is_nbt:
                n = n[0:3]  # Take only normal, skip binormal/tangent
            v = Vector(n)
            if v.length > 0:
                v.normalize()
            normals.append(tuple(v))
    return normals


def _extract_color_layers(source, face_list, faces, color_num):
    """Extract per-loop color and alpha layers from a vertex color attribute.

    In: source (sequence of color objects with .red/.green/.blue/.alpha 0..255); face_list (list[list[int]]); faces (list[list[int]]); color_num (str, '0' or '1', layer name suffix).
    Out: tuple (color_layer, alpha_layer) — both IRColorLayer with values in [0,1].
    """
    colors = []
    alphas = []
    for face_id, face in enumerate(faces):
        attr_face = face_list[face_id] if face_id < len(face_list) else face
        for vert_idx_in_face in range(len(face)):
            src_idx = attr_face[vert_idx_in_face]
            color = source[src_idx]
            r = color.red / 255.0
            g = color.green / 255.0
            b = color.blue / 255.0
            a = color.alpha / 255.0
            colors.append((r, g, b, a))
            alphas.append((a, a, a, 1.0))

    color_layer = IRColorLayer(name=f'color_{color_num}', colors=colors)
    alpha_layer = IRColorLayer(name=f'alpha_{color_num}', colors=alphas)
    return color_layer, alpha_layer


def _extract_bone_weights(pobj, joint, bone_index, bones, joint_to_bone_index, faces,
                          vertices_out, normals=None, validated_face_lists=None,
                          logger=StubLogger(), options=None):
    """Extract bone weight data from a PObject; envelope path also deforms vertices/normals.

    In: pobj (PObject, parsed); joint (Joint); bone_index (int, ≥0); bones (list[IRBone]); joint_to_bone_index (dict[int,int]); faces (list[list[int]]); vertices_out (list[tuple], mutated for envelope); normals (list[tuple]|None, mutated); validated_face_lists (list[list[list[int]]]|None); logger (Logger); options (dict|None).
    Out: IRBoneWeights (RIGID/SINGLE_BONE/WEIGHTED).
    """
    if pobj.property is None:
        # Rigid: attached to parent bone
        return IRBoneWeights(
            type=SkinType.RIGID,
            bone_name=bones[bone_index].name,
        )

    pobj_type = pobj.pobj_type_flag()

    if pobj_type == POBJ_ENVELOPE:
        return _extract_envelope_weights(
            pobj, joint, bone_index, bones, joint_to_bone_index, faces,
            vertices_out, normals, validated_face_lists, logger, options
        )
    elif pobj_type == POBJ_SKIN:
        # POBJ_SKIN ("singly-bound") — UNVERIFIED PATH.
        #
        # A corpus survey of shipped game PKXs (both XD and Colosseum)
        # found zero PObjs with this flag set, so this branch has never
        # fired on real assets and we have no test model to validate it.
        #
        # The vertex transform on line ~199 (`parent_world @ vert`) treats
        # SINGLE_BONE the same as RIGID, but that's almost certainly wrong:
        # HSDLib's ModelExporter.cs:439 transforms by `SingleBoundJOBJ`'s
        # WorldTransform, not the parent JObj's. The XD disassembly
        # (SetupSharedVtxModelMtx) loads two PNMTX slots and the runtime
        # semantics need more investigation. Fix when an asset that
        # exercises this path turns up.
        skin_joint = pobj.property
        skin_bone_idx = joint_to_bone_index.get(skin_joint.address, bone_index)
        return IRBoneWeights(
            type=SkinType.SINGLE_BONE,
            bone_name=bones[skin_bone_idx].name,
        )
    elif pobj_type == POBJ_SHAPEANIM:
        # Shape animation — rigid attachment to parent bone
        return IRBoneWeights(
            type=SkinType.RIGID,
            bone_name=bones[bone_index].name,
        )

    return IRBoneWeights(type=SkinType.RIGID, bone_name=bones[bone_index].name)


# --- Envelope helper functions (ported from legacy Mesh.py) ---

def _find_skeleton_bone(bone_index, bones):
    """Walk up the parent chain to find the first SKELETON or SKELETON_ROOT bone.

    In: bone_index (int, ≥0, starting bone); bones (list[IRBone]).
    Out: int|None — bone index of the matching ancestor, or None if no parent has the flag.
    """
    idx = bone_index
    while idx is not None:
        bone = bones[idx]
        if bone.flags & (JOBJ_SKELETON_ROOT | JOBJ_SKELETON):
            return idx
        idx = bone.parent_index
    return None


def _get_invbind_matrix(bone_index, bones):
    """Return the bone's inverse bind matrix, walking up parents if absent.

    In: bone_index (int, ≥0); bones (list[IRBone]).
    Out: Matrix (4×4); identity if no ancestor stores an inverse_bind_matrix.
    """
    idx = bone_index
    while idx is not None:
        bone = bones[idx]
        if bone.inverse_bind_matrix:
            return Matrix(bone.inverse_bind_matrix)
        idx = bone.parent_index
    return Matrix.Identity(4)


def _get_bind_world_matrix(bone_index, bones):
    """Return the bone's bind-time world matrix (IBM.inv() preferred, SRT world fallback).

    In: bone_index (int, ≥0); bones (list[IRBone]).
    Out: Matrix (4×4) suitable for envelope deformation.
    """
    bone = bones[bone_index]
    if bone.inverse_bind_matrix:
        return Matrix(bone.inverse_bind_matrix).inverted()
    return Matrix(bone.world_matrix)


def _envelope_coord_system(bone_index, bones):
    """Compute the envelope coordinate-system matrix for a bone, relative to its skeleton.

    In: bone_index (int, ≥0); bones (list[IRBone]).
    Out: Matrix (4×4)|None — None if bone is JOBJ_SKELETON_ROOT or no skeleton ancestor exists.
    """
    bone = bones[bone_index]
    if bone.flags & JOBJ_SKELETON_ROOT:
        return None

    skel_idx = _find_skeleton_bone(bone_index, bones)
    if skel_idx is None:
        return None

    inv_bind = _get_invbind_matrix(bone_index, bones)
    bone_world = Matrix(bone.world_matrix)

    if skel_idx == bone_index:
        # Skeleton root == this bone
        return inv_bind.inverted()
    elif bones[skel_idx].flags & JOBJ_SKELETON_ROOT:
        # Skeleton root is the actual root
        skel_world = Matrix(bones[skel_idx].world_matrix)
        return skel_world.inverted() @ bone_world
    else:
        # General case
        skel_world = Matrix(bones[skel_idx].world_matrix)
        return (skel_world @ inv_bind).inverted() @ bone_world


def _extract_envelope_weights(pobj, joint, bone_index, bones, joint_to_bone_index, faces,
                              vertices_out, normals=None, validated_face_lists=None,
                              logger=StubLogger(), options=None):
    """Extract weighted-envelope skinning, deforming vertices and normals in place.

    In: pobj (PObject, envelope type); joint (Joint); bone_index (int, ≥0); bones (list[IRBone]); joint_to_bone_index (dict[int,int]); faces (list[list[int]]); vertices_out (list[tuple], mutated); normals (list[tuple]|None, mutated); validated_face_lists (list[list[list[int]]]|None); logger (Logger); options (dict|None).
    Out: IRBoneWeights (WEIGHTED with per-vertex assignments, or RIGID fallback if PNMTXIDX missing).
    """
    envelope_list = pobj.property

    envelope_vertex_index = pobj.find_attribute_index(GX_VA_PNMTXIDX)
    if envelope_vertex_index is None:
        logger.leniency("envelope_no_pnmtxidx",
                        "PObj 0x%X has envelope descriptor bits but no PNMTXIDX attribute; game would deref garbage",
                        pobj.address)
        return IRBoneWeights(type=SkinType.RIGID, bone_name=bones[bone_index].name)

    env_source = pobj.sources[envelope_vertex_index]
    if validated_face_lists is not None:
        env_faces = validated_face_lists[envelope_vertex_index]
    else:
        env_faces = pobj.face_lists[envelope_vertex_index]

    indices = _build_vertex_to_envelope_map(faces, env_faces, env_source)
    coord = _envelope_coord_system(bone_index, bones)
    deform_matrices = _compute_envelope_deform_matrices(
        envelope_list, bones, joint_to_bone_index, coord, pobj.address, logger, options,
    )

    logger.debug("    envelope: bone=%s, %d verts, %d matrices, %d envs, %d faces",
                 bones[bone_index].name, len(indices), len(deform_matrices),
                 len(envelope_list), len(faces))

    new_vertices = _deform_vertices_by_envelope(vertices_out, deform_matrices, indices)
    vertices_out[:] = new_vertices

    if normals is not None:
        new_normals = _deform_normals_by_envelope(normals, deform_matrices, indices, faces)
        normals[:] = new_normals

    assignments = _build_envelope_weight_assignments(
        envelope_list, indices, bones, joint_to_bone_index,
    )
    return IRBoneWeights(type=SkinType.WEIGHTED, assignments=assignments)


def _build_vertex_to_envelope_map(faces, env_faces, env_source):
    """Map each position-vertex index to its envelope index via face-list parallelism.

    In: faces (list[list[int]], position face list); env_faces (list[list[int]], PNMTXIDX face list, may be shorter); env_source (sequence[int], raw PNMTXIDX values; envelope index = value//3).
    Out: dict[int, int] — vertex index → envelope index for every vertex covered by both face lists.
    """
    indices = {}
    for face_id, face in enumerate(faces):
        if face_id < len(env_faces):
            env_face = env_faces[face_id]
            for vert_idx, global_vert in enumerate(face):
                if vert_idx < len(env_face):
                    indices[global_vert] = env_source[env_face[vert_idx]] // 3
    return indices


def _compute_envelope_deform_matrix(envelope, bones, joint_to_bone_index, coord):
    """Compute the deformation matrix for a single envelope (single- or multi-weight).

    In: envelope (Envelope node with .envelopes list of weight/joint entries); bones (list[IRBone]); joint_to_bone_index (dict[int,int]); coord (Matrix|None — envelope coord system; None ⇒ skeleton-root path).
    Out: Matrix (4×4) — the per-envelope deformation matrix to apply to verts.
    """
    entries = [(entry.weight, entry.joint) for entry in envelope.envelopes]
    if entries[0][0] == 1.0:
        entry_joint = entries[0][1]
        entry_bone_idx = joint_to_bone_index.get(entry_joint.address, 0)
        entry_world = Matrix(bones[entry_bone_idx].world_matrix)
        if coord:
            entry_invbind = _get_invbind_matrix(entry_bone_idx, bones)
            matrix = entry_world @ entry_invbind
        else:
            # Skeleton-root case: HSD engine uses world matrix only, no IBM.
            matrix = entry_world
    else:
        matrix = Matrix([[0] * 4 for _ in range(4)])
        for weight, entry_joint in entries:
            entry_bone_idx = joint_to_bone_index.get(entry_joint.address, 0)
            entry_world = Matrix(bones[entry_bone_idx].world_matrix)
            entry_invbind = _get_invbind_matrix(entry_bone_idx, bones)
            contrib = entry_world @ entry_invbind
            for i in range(4):
                for j in range(4):
                    matrix[i][j] += weight * contrib[i][j]

    if coord:
        matrix = matrix @ coord
    return matrix


def _compute_envelope_deform_matrices(envelope_list, bones, joint_to_bone_index, coord,
                                      pobj_addr, logger, options):
    """Compute one deform matrix per envelope, reporting weight-cap violations.

    In: envelope_list (list[Envelope]); bones (list[IRBone]); joint_to_bone_index (dict[int,int]); coord (Matrix|None); pobj_addr (int, for the leniency report); logger (Logger); options (dict|None).
    Out: list[Matrix] — one 4×4 matrix per envelope, in the same order.
    """
    matrices = []
    for env_idx, envelope in enumerate(envelope_list):
        if len(envelope.envelopes) > 10:
            logger.leniency("envelope_over_cap",
                            "PObj 0x%X envelope %d has %d weights (game caps at 10)",
                            pobj_addr, env_idx, len(envelope.envelopes))
        matrices.append(_compute_envelope_deform_matrix(envelope, bones, joint_to_bone_index, coord))
    return matrices


def _deform_vertices_by_envelope(vertices, deform_matrices, indices):
    """Apply per-vertex envelope deformation, returning a new vertex list.

    In: vertices (list[tuple[float,float,float]]); deform_matrices (list[Matrix]); indices (dict[int,int], vertex idx → envelope idx).
    Out: list[tuple[float,float,float]] — same length, deformed where indices reference a valid envelope.
    """
    out = list(vertices)
    for vertex_idx, env_idx in indices.items():
        if env_idx < len(deform_matrices):
            new_pos = deform_matrices[env_idx] @ Vector(out[vertex_idx])
            out[vertex_idx] = tuple(new_pos)
    return out


def _deform_normals_by_envelope(normals, deform_matrices, indices, faces):
    """Apply inverse-transpose envelope deformation to per-loop normals.

    In: normals (list[tuple[float,float,float]], one per loop); deform_matrices (list[Matrix]); indices (dict[int,int]); faces (list[list[int]], drives loop ordering).
    Out: list[tuple[float,float,float]] — same length as `normals`, normalized after transform.
    """
    normal_matrices = []
    for dm in deform_matrices:
        nm = dm.to_3x3()
        nm.invert()
        nm.transpose()
        normal_matrices.append(nm.to_4x4())

    out = list(normals)
    loop_idx = 0
    for face in faces:
        for vert_idx in face:
            env_idx = indices.get(vert_idx)
            if env_idx is not None and env_idx < len(normal_matrices):
                new_n = (normal_matrices[env_idx] @ Vector(out[loop_idx])).normalized()
                out[loop_idx] = tuple(new_n)
            loop_idx += 1
    return out


def _build_envelope_weight_assignments(envelope_list, indices, bones, joint_to_bone_index):
    """Build per-vertex (bone_name, weight) assignments from envelope entries.

    In: envelope_list (list[Envelope]); indices (dict[int,int], vertex idx → envelope idx); bones (list[IRBone]); joint_to_bone_index (dict[int,int]).
    Out: list[tuple[int, list[tuple[str, float]]]] — sorted by vertex index, weights as (bone_name, weight) pairs.
    """
    assignments = []
    for vertex_idx, env_idx in sorted(indices.items()):
        if env_idx < len(envelope_list):
            weights = []
            for entry in envelope_list[env_idx].envelopes:
                entry_bone_idx = joint_to_bone_index.get(entry.joint.address, 0)
                weights.append((bones[entry_bone_idx].name, entry.weight))
            assignments.append((vertex_idx, weights))
    return assignments
