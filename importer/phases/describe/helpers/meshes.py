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


def describe_meshes(root_joint, bones, joint_to_bone_index, image_cache=None, logger=StubLogger()):
    """Walk Joint tree, extract geometry from Mesh→PObject chains.

    Args:
        root_joint: Root Joint node from the parsed node tree.
        bones: list[IRBone] from describe_bones().
        joint_to_bone_index: dict mapping Joint.address → index in bones list.
        image_cache: dict for deduplicating images by (image_id, palette_id).
        logger: Logger instance (defaults to StubLogger).

    Returns:
        list[IRMesh] with geometry data extracted.
    """
    if image_cache is None:
        image_cache = {}
    meshes = []
    mesh_count = [0]
    material_cache = {}  # {mobject.address: IRMaterial} — dedup shared materials

    def _walk_joints(joint):
        bone_index = joint_to_bone_index.get(joint.address, 0)
        bone = bones[bone_index]

        if joint.property is not None and hasattr(joint.property, 'pobject'):
            _walk_mesh_chain(joint.property, joint, bone_index)

        if joint.child and not (joint.flags & (1 << 12)):  # JOBJ_INSTANCE
            _walk_joints(joint.child)
        if joint.next:
            _walk_joints(joint.next)

    def _walk_mesh_chain(mesh_node, joint, bone_index):
        """Walk the Mesh (DObject) linked list."""
        import time
        while mesh_node:
            # Describe the material for this DObject (cached by mobject address)
            ir_material = None
            if mesh_node.mobject:
                mob_addr = mesh_node.mobject.address
                if mob_addr in material_cache:
                    ir_material = material_cache[mob_addr]
                    logger.debug("    reusing cached IRMaterial for DObj 0x%X (mob 0x%X)", mesh_node.address, mob_addr)
                else:
                    from .materials import describe_material
                    t = time.time()
                    ir_material = describe_material(mesh_node.mobject, image_cache=image_cache)
                    logger.debug("    describe_material for DObj 0x%X: %.3fs", mesh_node.address, time.time() - t)
                    material_cache[mob_addr] = ir_material

            pobj = mesh_node.pobject
            while pobj:
                t = time.time()
                ir_mesh = _describe_pobj(pobj, joint, bone_index, mesh_count[0], ir_material)
                logger.debug("    describe_pobj 0x%X: %.3fs", pobj.address, time.time() - t)
                if ir_mesh is not None:
                    bones[bone_index].mesh_indices.append(len(meshes))
                    meshes.append(ir_mesh)
                    mesh_count[0] += 1
                pobj = pobj.next
            mesh_node = mesh_node.next

    def _describe_pobj(pobj, joint, bone_index, count, ir_material=None):
        """Extract geometry from a single PObject into an IRMesh."""
        vertex_list = pobj.vertex_list.vertices

        # Find position vertex index
        pos_idx = None
        for i, vertex in enumerate(vertex_list):
            if vertex.attribute == GX_VA_POS:
                pos_idx = i
                break

        if pos_idx is None:
            return None

        vertices = list(pobj.sources[pos_idx])
        faces = list(pobj.face_lists[pos_idx])

        # Validate: remove degenerate faces
        face_lists_copy = [list(fl) for fl in pobj.face_lists]
        orig_face_count = len(faces)
        face_lists_copy, faces = _validate_mesh(face_lists_copy, faces)
        if len(faces) != orig_face_count:
            logger.debug("  pobj 0x%X mesh#%d: removed %d degenerate faces (%d → %d)",
                         pobj.address, count, orig_face_count - len(faces), orig_face_count, len(faces))

        # Convert vertices to tuples and scale to meters
        verts_out = [tuple(c * GC_TO_METERS for c in v) for v in vertices]

        # Extract UV layers, color layers, normals
        uv_layers = []
        color_layers = []
        normals = None

        for i, vertex in enumerate(vertex_list):
            if vertex.isTexture():
                tex_idx = vertex.attribute - GX_VA_TEX0
                uv_layer = _extract_uv_layer(
                    pobj.sources[i], face_lists_copy[i], faces, tex_idx
                )
                uv_layers.append(uv_layer)

            elif vertex.attribute in (GX_VA_NRM, GX_VA_NBT):
                normals = _extract_normals(
                    pobj.sources[i], face_lists_copy[i], faces,
                    is_nbt=(vertex.attribute == GX_VA_NBT)
                )

            elif vertex.attribute in (GX_VA_CLR0, GX_VA_CLR1):
                color_num = '0' if vertex.attribute == GX_VA_CLR0 else '1'
                color_layer, alpha_layer = _extract_color_layers(
                    pobj.sources[i], face_lists_copy[i], faces, color_num
                )
                color_layers.append(color_layer)
                color_layers.append(alpha_layer)

        # Add default white color/alpha layers if CLR0 not present
        has_color_0 = any(cl.name == 'color_0' for cl in color_layers)
        has_alpha_0 = any(cl.name == 'alpha_0' for cl in color_layers)
        total_loops = sum(len(f) for f in faces)
        if not has_color_0:
            color_layers.append(IRColorLayer(
                name='color_0',
                colors=[(1.0, 1.0, 1.0, 1.0)] * total_loops,
            ))
        if not has_alpha_0:
            color_layers.append(IRColorLayer(
                name='alpha_0',
                colors=[(1.0, 1.0, 1.0, 1.0)] * total_loops,
            ))

        # Extract bone weight info (may deform verts_out and normals in-place for envelopes)
        bone_weights = _extract_bone_weights(
            pobj, joint, bone_index, bones, joint_to_bone_index, faces,
            verts_out, normals, face_lists_copy, logger
        )

        # For non-envelope meshes (RIGID, SINGLE_BONE), vertices are in the
        # parent bone's local space. Transform to world space so the IR
        # consistently stores world-space vertices for all skin types.
        # Envelope vertices are already in world space (deformed above).
        if bone_weights and bone_weights.type in (SkinType.RIGID, SkinType.SINGLE_BONE):
            parent_world = Matrix(bones[bone_index].world_matrix)
            for vi in range(len(verts_out)):
                verts_out[vi] = tuple(parent_world @ Vector(verts_out[vi]))

        name = pobj.name if pobj.name else str(count)

        return IRMesh(
            name=name,
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

    _walk_joints(root_joint)

    # Pad numeric mesh names based on total count
    if meshes:
        digits = len(str(len(meshes) - 1))
        for mesh in meshes:
            if mesh.name.isdigit():
                mesh.name = mesh.name.zfill(digits)

    return meshes


def _validate_mesh(face_lists, faces):
    """Remove faces with repeated vertices (degenerate tri-strip artifacts)."""
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
    """Extract UV coordinates with V-flip, per-loop order.

    Iterates over faces (position face list) for polygon structure,
    using face_list (UV attribute face list) for source index lookup.
    This matches how Blender loops correspond to polygon vertices.
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
    """Extract per-loop normals as normalized tuples."""
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
    """Extract color and alpha layers from vertex color data."""
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
                          logger=StubLogger()):
    """Extract bone weight data from PObject property.

    For envelope-weighted meshes, also deforms vertices_out and normals
    in-place using the envelope matrices (matching legacy Mesh.apply_bone_weights).

    Args:
        vertices_out: mutable list of vertex positions — may be modified in-place
                      for envelope deformation.
        normals: mutable list of per-loop normals — may be modified in-place
                 for envelope normal transformation.
        validated_face_lists: face lists with degenerate faces removed (must be
                             used for envelope index lookup to stay in sync with
                             the validated position faces).
    """
    if pobj.property is None:
        # Rigid: attached to parent bone
        return IRBoneWeights(
            type=SkinType.RIGID,
            bone_name=bones[bone_index].name,
        )

    pobj_type = pobj.flags & POBJ_TYPE_MASK

    if pobj_type == POBJ_ENVELOPE:
        return _extract_envelope_weights(
            pobj, joint, bone_index, bones, joint_to_bone_index, faces,
            vertices_out, normals, validated_face_lists, logger
        )
    elif pobj_type == POBJ_SKIN:
        # Single bone deformation
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
    """Walk up the parent chain to find the first bone with SKELETON or SKELETON_ROOT flag."""
    idx = bone_index
    while idx is not None:
        bone = bones[idx]
        if bone.flags & (JOBJ_SKELETON_ROOT | JOBJ_SKELETON):
            return idx
        idx = bone.parent_index
    return None


def _get_invbind_matrix(bone_index, bones):
    """Get the inverse bind matrix, walking up parents if the bone doesn't have one."""
    idx = bone_index
    while idx is not None:
        bone = bones[idx]
        if bone.inverse_bind_matrix:
            return Matrix(bone.inverse_bind_matrix)
        idx = bone.parent_index
    return Matrix.Identity(4)


def _get_bind_world_matrix(bone_index, bones):
    """Get the bone's world matrix at bind time for envelope deformation.

    For bones with an IBM, use IBM.inv() as the authoritative bind-time world
    matrix. This ensures deform = world @ IBM = identity at rest pose, regardless
    of whether our SRT-computed world_matrix exactly matches the IBM. The IBM
    may encode IK-solved positions, parent scale effects, or other runtime
    adjustments not captured by pure SRT composition.

    For bones without an IBM, fall back to the SRT-computed world_matrix.
    """
    bone = bones[bone_index]
    if bone.inverse_bind_matrix:
        return Matrix(bone.inverse_bind_matrix).inverted()
    return Matrix(bone.world_matrix)


def _envelope_coord_system(bone_index, bones):
    """Compute envelope coordinate system matrix for a bone.

    Ports legacy envelope_coord_system() to work with flat IRBone list.
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
                              logger=StubLogger()):
    """Extract weighted envelope deformation data, deform vertices and normals."""
    vertex_list = pobj.vertex_list.vertices
    envelope_list = pobj.property

    # Find the PNMTXIDX vertex attribute (envelope index source)
    envelope_vertex_index = None
    for i, vertex in enumerate(vertex_list):
        if vertex.attribute == GX_VA_PNMTXIDX:
            envelope_vertex_index = i
            break

    if envelope_vertex_index is None:
        return IRBoneWeights(type=SkinType.RIGID, bone_name=bones[bone_index].name)

    env_source = pobj.sources[envelope_vertex_index]
    # Use validated face lists (degenerate faces removed) to stay in sync
    # with the validated position faces. Legacy modifies face_lists in-place
    # before calling make_deform_skin; we must use the same validated lists.
    if validated_face_lists is not None:
        env_faces = validated_face_lists[envelope_vertex_index]
    else:
        env_faces = pobj.face_lists[envelope_vertex_index]

    # Build vertex → envelope index mapping from face data
    indices = {}
    for face_id, face in enumerate(faces):
        if face_id < len(env_faces):
            env_face = env_faces[face_id]
            for vert_idx, global_vert in enumerate(face):
                if vert_idx < len(env_face):
                    indices[global_vert] = env_source[env_face[vert_idx]] // 3

    # Compute envelope coord system for the owning bone
    coord = _envelope_coord_system(bone_index, bones)

    # Compute per-envelope deformation matrices.
    # Formula: deform = (bone_world @ bone_IBM) [@ coord]
    #
    # The SRT-computed world_matrix may differ from IBM.inv() for some
    # bones (IK targets, certain parent scale chains). However, the edit
    # bone positions in Blender are ALSO derived from the SRT world matrix.
    # Using IBM.inv() here would make deformation identity at rest but
    # create a mismatch with the edit bones, causing garbled geometry under
    # the armature modifier. By using the SRT world matrix consistently,
    # the deformation error matches the edit bone error and they cancel out.
    deform_matrices = []
    for envelope in envelope_list:
        entries = [(entry.weight, entry.joint) for entry in envelope.envelopes]
        zero = [[0] * 4 for _ in range(4)]
        matrix = Matrix(zero)

        if entries[0][0] == 1.0:
            # Single-weight envelope
            entry_joint = entries[0][1]
            entry_bone_idx = joint_to_bone_index.get(entry_joint.address, 0)
            entry_world = Matrix(bones[entry_bone_idx].world_matrix)
            if coord:
                entry_invbind = _get_invbind_matrix(entry_bone_idx, bones)
                matrix = entry_world @ entry_invbind
            else:
                # When coord is None (skeleton root owns the mesh), the HSD
                # engine uses just the world matrix without IBM for single-weight
                # envelopes. This matches the legacy import_hsd.py behavior.
                matrix = entry_world
        else:
            # Multi-weight envelope
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
        deform_matrices.append(matrix)

    # Deform vertex positions in-place
    logger.debug("    envelope: bone=%s, %d verts, %d matrices, %d envs, %d faces",
                 bones[bone_index].name, len(indices), len(deform_matrices), len(envelope_list), len(faces))
    for vertex_idx, env_idx in indices.items():
        if env_idx < len(deform_matrices):
            old_pos = vertices_out[vertex_idx]
            new_pos = deform_matrices[env_idx] @ Vector(old_pos)
            if vertex_idx < 3:
                logger.debug("    envelope v%d: (%.4f,%.4f,%.4f) -> (%.4f,%.4f,%.4f) env=%d",
                             vertex_idx, old_pos[0], old_pos[1], old_pos[2],
                             new_pos[0], new_pos[1], new_pos[2], env_idx)
            vertices_out[vertex_idx] = tuple(new_pos)

    # Transform normals by inverse-transpose of deformation matrices
    # (normal matrix = inverse transpose of the 3x3 part of the deform matrix)
    if normals:
        normal_matrices = []
        for dm in deform_matrices:
            nm = dm.to_3x3()
            nm.invert()
            nm.transpose()
            normal_matrices.append(nm.to_4x4())

        loop_idx = 0
        for face in faces:
            for vert_idx in face:
                env_idx = indices.get(vert_idx)
                if env_idx is not None and env_idx < len(normal_matrices):
                    old_n = Vector(normals[loop_idx])
                    new_n = (normal_matrices[env_idx] @ old_n).normalized()
                    normals[loop_idx] = tuple(new_n)
                loop_idx += 1

    # Build per-vertex bone weight assignments
    assignments = []
    for vertex_idx, env_idx in sorted(indices.items()):
        if env_idx < len(envelope_list):
            envelope = envelope_list[env_idx]
            weights = []
            for entry in envelope.envelopes:
                entry_joint = entry.joint
                entry_bone_idx = joint_to_bone_index.get(entry_joint.address, 0)
                weights.append((bones[entry_bone_idx].name, entry.weight))
            assignments.append((vertex_idx, weights))

    return IRBoneWeights(
        type=SkinType.WEIGHTED,
        assignments=assignments,
    )
