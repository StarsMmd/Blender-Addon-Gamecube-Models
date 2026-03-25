"""Describe Joint→Mesh→PObject chains as IRMesh dataclasses.

Extracts geometry (vertices, faces, UVs, colors, normals) and bone weight
classification from parsed PObject nodes without any bpy calls.
"""
try:
    from ...shared.helpers.math_shim import Matrix, Vector
    from ...shared.IR.geometry import IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights, IRShapeKey
    from ...shared.IR.enums import SkinType
    from ...shared.Constants.hsd import (
        POBJ_TYPE_MASK, POBJ_SKIN, POBJ_ENVELOPE, POBJ_SHAPEANIM,
        JOBJ_SKELETON, JOBJ_SKELETON_ROOT, JOBJ_HIDDEN,
    )
    from ...shared.Constants.gx import (
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


def describe_meshes(root_joint, bones, joint_to_bone_index):
    """Walk Joint tree, extract geometry from Mesh→PObject chains.

    Args:
        root_joint: Root Joint node from the parsed node tree.
        bones: list[IRBone] from describe_bones().
        joint_to_bone_index: dict mapping Joint.address → index in bones list.

    Returns:
        list[IRMesh] with geometry data extracted.
    """
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
        while mesh_node:
            pobj = mesh_node.pobject
            while pobj:
                ir_mesh = _describe_pobj(pobj, joint, bone_index, mesh_count[0])
                if ir_mesh is not None:
                    bones[bone_index].mesh_indices.append(len(meshes))
                    meshes.append(ir_mesh)
                    mesh_count[0] += 1
                pobj = pobj.next
            mesh_node = mesh_node.next

    def _describe_pobj(pobj, joint, bone_index, count):
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

        # Extract bone weight info
        bone_weights = _extract_bone_weights(
            pobj, joint, bone_index, bones, joint_to_bone_index, faces
        )

        name = pobj.name if pobj.name else str(count)

        return IRMesh(
            name=name,
            vertices=verts_out,
            faces=faces,
            uv_layers=uv_layers,
            color_layers=color_layers,
            normals=normals,
            material=None,  # Filled in Step 2
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
    """Extract UV coordinates with V-flip, per-loop order."""
    uvs = []
    for face_id, face in enumerate(faces):
        attr_face = face_list[face_id] if face_id < len(face_list) else face
        for vert_idx_in_face in range(len(face)):
            src_idx = attr_face[vert_idx_in_face]
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


def _extract_bone_weights(pobj, joint, bone_index, bones, joint_to_bone_index, faces):
    """Extract bone weight data from PObject property."""
    if pobj.property is None:
        # Rigid: attached to parent bone
        return IRBoneWeights(
            type=SkinType.RIGID,
            bone_name=bones[bone_index].name,
        )

    pobj_type = pobj.flags & POBJ_TYPE_MASK

    if pobj_type == POBJ_ENVELOPE:
        return _extract_envelope_weights(
            pobj, joint, bone_index, bones, joint_to_bone_index, faces
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


def _extract_envelope_weights(pobj, joint, bone_index, bones, joint_to_bone_index, faces):
    """Extract weighted envelope deformation data."""
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

    # Build vertex → envelope index mapping from face data
    pos_idx = None
    for i, vertex in enumerate(vertex_list):
        if vertex.attribute == GX_VA_POS:
            pos_idx = i
            break

    env_source = pobj.sources[envelope_vertex_index]
    env_faces = pobj.face_lists[envelope_vertex_index]

    indices = {}
    for face_id, face in enumerate(faces):
        if face_id < len(env_faces):
            env_face = env_faces[face_id]
            for vert_idx, global_vert in enumerate(face):
                if vert_idx < len(env_face):
                    indices[global_vert] = env_source[env_face[vert_idx]] // 3

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
