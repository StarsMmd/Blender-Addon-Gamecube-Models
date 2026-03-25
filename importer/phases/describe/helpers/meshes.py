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
        JOBJ_SKELETON, JOBJ_SKELETON_ROOT, JOBJ_HIDDEN,
    )
    from .....shared.Constants.gx import (
        GX_VA_POS, GX_VA_NRM, GX_VA_NBT, GX_VA_CLR0, GX_VA_CLR1,
        GX_VA_TEX0, GX_VA_PNMTXIDX,
    )
except (ImportError, SystemError):
    from shared.helpers.math_shim import Matrix, Vector
    from shared.IR.geometry import IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights, IRShapeKey
    from shared.IR.enums import SkinType
    from shared.Constants.hsd import (
        POBJ_TYPE_MASK, POBJ_SKIN, POBJ_ENVELOPE, POBJ_SHAPEANIM,
        JOBJ_SKELETON, JOBJ_SKELETON_ROOT, JOBJ_HIDDEN,
    )
    from shared.Constants.gx import (
        GX_VA_POS, GX_VA_NRM, GX_VA_NBT, GX_VA_CLR0, GX_VA_CLR1,
        GX_VA_TEX0, GX_VA_PNMTXIDX,
    )


def describe_meshes(root_joint, bones, joint_to_bone_index, image_cache=None, logger=None):
    """Walk Joint tree, extract geometry from Mesh→PObject chains.

    Args:
        root_joint: Root Joint node from the parsed node tree.
        bones: list[IRBone] from describe_bones().
        joint_to_bone_index: dict mapping Joint.address → index in bones list.
        image_cache: dict for deduplicating images by (image_id, palette_id).
        logger: Logger instance (defaults to NullLogger).

    Returns:
        list[IRMesh] with geometry data extracted.
    """
    if image_cache is None:
        image_cache = {}
    if logger is None:
        try:
            from .....shared.IO.Logger import NullLogger
        except (ImportError, SystemError):
            from shared.IO.Logger import NullLogger
        logger = NullLogger()
    meshes = []
    mesh_count = [0]

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
            # Describe the material for this DObject
            ir_material = None
            if mesh_node.mobject:
                from .materials import describe_material
                t = time.time()
                ir_material = describe_material(mesh_node.mobject, image_cache=image_cache)
                logger.debug("    describe_material for DObj 0x%X: %.3fs", mesh_node.address, time.time() - t)

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
        face_lists_copy, faces = _validate_mesh(face_lists_copy, faces)

        # Convert vertices to tuples
        verts_out = [tuple(v) for v in vertices]

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

        # Extract bone weight info (may deform verts_out in-place for envelopes)
        bone_weights = _extract_bone_weights(
            pobj, joint, bone_index, bones, joint_to_bone_index, faces,
            verts_out
        )

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
        )

    _walk_joints(root_joint)
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
                          vertices_out):
    """Extract bone weight data from PObject property.

    For envelope-weighted meshes, also deforms vertices_out in-place using
    the envelope matrices (matching legacy Mesh.apply_bone_weights).

    Args:
        vertices_out: mutable list of vertex positions — may be modified in-place
                      for envelope deformation.
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
            vertices_out
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
                              vertices_out):
    """Extract weighted envelope deformation data and deform vertices."""
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

    # Compute per-envelope deformation matrices (matching legacy Mesh.apply_bone_weights)
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
            entry_invbind = _get_invbind_matrix(entry_bone_idx, bones)
            if coord:
                matrix = entry_world @ entry_invbind
            else:
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
    for vertex_idx, env_idx in indices.items():
        if env_idx < len(deform_matrices):
            old_pos = vertices_out[vertex_idx]
            new_pos = deform_matrices[env_idx] @ Vector(old_pos)
            vertices_out[vertex_idx] = tuple(new_pos)

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
