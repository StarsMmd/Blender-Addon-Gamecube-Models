"""Compose IRMesh list into Mesh → PObject → VertexList → Vertex node chains.

Reverses importer/phases/describe/helpers/meshes.py:describe_meshes().
Takes IRMesh dataclasses and reconstructs the SysDolphin node tree
structure with encoded vertex buffers and GX display lists.
"""
import re
from collections import defaultdict

try:
    from .....shared.Nodes.Classes.Mesh.Mesh import Mesh
    from .....shared.Nodes.Classes.Mesh.PObject import PObject
    from .....shared.Nodes.Classes.Mesh.VertexList import VertexList
    from .....shared.Nodes.Classes.Mesh.Vertex import Vertex
    from .....shared.Nodes.Classes.Joints.Envelope import EnvelopeList, Envelope
    from .....shared.Constants.gx import (
        GX_VA_POS, GX_VA_NRM, GX_VA_CLR0, GX_VA_CLR1,
        GX_VA_TEX0, GX_VA_PNMTXIDX,
        GX_INDEX16, GX_DIRECT, GX_F32, GX_RGBA8,
        GX_POS_XYZ, GX_NRM_XYZ, GX_TEX_ST,
        GX_DRAW_TRIANGLES, GX_DRAW_QUADS,
    )
    from .....shared.Constants.hsd import (
        POBJ_CULLFRONT, POBJ_CULLBACK, POBJ_SKIN, POBJ_ENVELOPE,
        JOBJ_HIDDEN, JOBJ_SKELETON, JOBJ_SKELETON_ROOT,
    )
    from .....shared.IR.enums import SkinType
    from .....shared.helpers.binary import pack, pack_many
    from .....shared.helpers.math_shim import Matrix, Vector
    from .....shared.helpers.logger import StubLogger
    from .materials import compose_material
except (ImportError, SystemError):
    from shared.Nodes.Classes.Mesh.Mesh import Mesh
    from shared.Nodes.Classes.Mesh.PObject import PObject
    from shared.Nodes.Classes.Mesh.VertexList import VertexList
    from shared.Nodes.Classes.Mesh.Vertex import Vertex
    from shared.Nodes.Classes.Joints.Envelope import EnvelopeList, Envelope
    from shared.Constants.gx import (
        GX_VA_POS, GX_VA_NRM, GX_VA_CLR0, GX_VA_CLR1,
        GX_VA_TEX0, GX_VA_PNMTXIDX,
        GX_INDEX16, GX_DIRECT, GX_F32, GX_RGBA8,
        GX_POS_XYZ, GX_NRM_XYZ, GX_TEX_ST,
        GX_DRAW_TRIANGLES, GX_DRAW_QUADS,
    )
    from shared.Constants.hsd import (
        POBJ_CULLFRONT, POBJ_CULLBACK, POBJ_SKIN, POBJ_ENVELOPE,
        JOBJ_HIDDEN, JOBJ_SKELETON, JOBJ_SKELETON_ROOT,
    )
    from shared.IR.enums import SkinType
    from shared.helpers.binary import pack, pack_many
    from shared.helpers.math_shim import Matrix, Vector
    from shared.helpers.logger import StubLogger
    from exporter.phases.compose.helpers.materials import compose_material


# Counter for generating unique synthetic base_pointer values.
# Each vertex buffer needs a distinct base_pointer so the VertexList
# deduplication logic treats them as separate buffers during serialization.
_next_synthetic_bp = [0x80000000]


def _alloc_base_pointer():
    """Allocate a unique synthetic base_pointer for a vertex buffer."""
    bp = _next_synthetic_bp[0]
    _next_synthetic_bp[0] += 0x10000
    return bp


def compose_meshes(meshes, joints, bones, logger=StubLogger()):
    """Convert IRMesh list into Mesh node chains attached to Joints.

    Groups meshes by parent_bone_index. Within each bone, meshes that
    share the same material are grouped under one DObject (Mesh node)
    with PObjects chained via PObject.next. Different materials get
    separate DObjects linked via Mesh.next. This matches the HSD
    convention where a DObject owns one material and one or more PObjects.

    Args:
        meshes: list[IRMesh] from the IR.
        joints: list[Joint] indexed by bone index (from compose_bones).
        bones: list[IRBone] from the IR (for bone name lookup).
        logger: Logger instance.

    Returns:
        None (mutates joints in-place by setting joint.property).
    """
    if not meshes or not joints:
        return

    # Reset synthetic base_pointer counter for each compose call
    _next_synthetic_bp[0] = 0x80000000

    # Group meshes by parent bone
    meshes_by_bone = defaultdict(list)
    for ir_mesh in meshes:
        bone_idx = ir_mesh.parent_bone_index
        if bone_idx < len(joints):
            meshes_by_bone[bone_idx].append(ir_mesh)

    bone_name_to_index = {bone.name: i for i, bone in enumerate(bones)}

    # Dedup MObject subtrees across DObjects. Keyed on id(ir_material), so
    # every DObject whose IRMesh references the same IRMaterial instance
    # (typically produced by describe_blender's material_cache) points at
    # the same MaterialObject node. The serialize DFS then writes the
    # MObject + its TObject + Image + pixel data exactly once.
    mobj_cache = {}

    for bone_idx, ir_meshes in meshes_by_bone.items():
        # Group IRMeshes by material identity. Meshes with the same
        # material (by id) share a DObject; each gets its own PObject.
        # Preserve original order: use the first occurrence of each
        # material id as the group key order.
        material_groups = []  # [(material_id, [ir_mesh, ...])]
        mat_id_to_group = {}
        for ir_mesh in ir_meshes:
            mat_id = id(ir_mesh.material)
            if mat_id not in mat_id_to_group:
                group = []
                mat_id_to_group[mat_id] = group
                material_groups.append((ir_mesh.material, group))
            mat_id_to_group[mat_id].append(ir_mesh)

        mesh_nodes = []
        for ir_material, group_meshes in material_groups:
            # Build PObjects for each mesh in this material group
            pobjs = []
            for ir_mesh in group_meshes:
                result = _build_pobj(ir_mesh, joints, bones, bone_name_to_index, logger)
                if result is not None:
                    pobjs.extend(result)

            if not pobjs:
                continue

            # Chain PObjects via .next under one DObject
            for i in range(len(pobjs) - 1):
                pobjs[i].next = pobjs[i + 1]

            mat_key = id(ir_material)
            mobj = mobj_cache.get(mat_key)
            if mobj is None:
                mobj = compose_material(ir_material, logger=logger)
                mobj_cache[mat_key] = mobj

            mesh_node = Mesh(address=None, blender_obj=None)
            mesh_node.name = None
            mesh_node.next = None
            mesh_node.mobject = mobj
            mesh_node.pobject = pobjs[0]
            mesh_nodes.append(mesh_node)

        if not mesh_nodes:
            continue

        # Link DObject nodes into a linked list via .next
        for i in range(len(mesh_nodes) - 1):
            mesh_nodes[i].next = mesh_nodes[i + 1]

        # Attach to joint
        joints[bone_idx].property = mesh_nodes[0]

        # If all meshes on this bone are hidden, set JOBJ_HIDDEN on the joint
        if all(m.is_hidden for m in ir_meshes):
            joints[bone_idx].flags |= JOBJ_HIDDEN

    total_meshes = sum(len(ml) for ml in meshes_by_bone.values())
    logger.info("    Composed %d meshes across %d bones", total_meshes, len(meshes_by_bone))
    for bone_idx, ir_meshes in meshes_by_bone.items():
        bone_name = bones[bone_idx].name if bone_idx < len(bones) else '?'
        logger.debug("      bone[%d] '%s': %d mesh(es)", bone_idx, bone_name, len(ir_meshes))


def _build_pobj(ir_mesh, joints, bones, bone_name_to_index, logger):
    """Build PObject node(s) from an IRMesh.

    Creates vertex descriptors, encodes vertex buffer data, and builds
    GX display list(s) for the geometry. If the mesh has more than 10
    unique envelope (bone weight) combinations, it is split into multiple
    PObjects — one per group of ≤10 envelopes — since the GX hardware
    only has 10 position/normal matrix slots per draw call.

    Returns:
        list[PObject], or None if the mesh has no geometry.
    """
    if not ir_mesh.vertices or not ir_mesh.faces:
        return None

    bw = ir_mesh.bone_weights
    is_envelope = bw and bw.type == SkinType.WEIGHTED and bw.assignments

    # Build vertex descriptors and encode vertex/display list data
    vertex_descs = []
    vertex_buffers = []

    # PNMTXIDX — envelope index attribute (only for WEIGHTED meshes)
    envelope_map = None
    if is_envelope:
        envelope_map = _build_envelope_map(bw.assignments, bone_name_to_index, logger=logger)
        pnmtx_desc = Vertex(address=None, blender_obj=None)
        pnmtx_desc.attribute = GX_VA_PNMTXIDX
        pnmtx_desc.attribute_type = GX_DIRECT
        pnmtx_desc.component_count = 0
        pnmtx_desc.component_type = GX_F32
        pnmtx_desc.component_frac = 0
        pnmtx_desc.stride = 0
        pnmtx_desc.base_pointer = 0
        pnmtx_desc.raw_vertex_data = b''
        vertex_descs.append(pnmtx_desc)
        vertex_buffers.append(('pnmtxidx', envelope_map))

    # Position — always present.
    # The IR stores vertices in world space. The DAT format stores them
    # relative to the parent bone's transform:
    # - WEIGHTED (envelope): reverse the deformation (bone_world @ IBM @ coord)
    # - SINGLE_BONE: transform from world to parent bone's local space
    export_vertices = ir_mesh.vertices
    if is_envelope and bones:
        export_vertices = _undeform_vertices(
            ir_mesh.vertices, envelope_map, bones, bone_name_to_index,
            ir_mesh.parent_bone_index, logger)
    elif bw and bw.type in (SkinType.SINGLE_BONE, SkinType.RIGID) and bones:
        # SINGLE_BONE and RIGID: transform from world space to the parent
        # JObj's local space. The game applies parent_jobj.world at render
        # time to position the mesh — this must mirror the importer, which
        # also uses parent_bone_index (not bw.bone_name) for both types.
        # Using bw.bone_name here would break meshes whose original
        # attachment bone differs from their single weight target (e.g.
        # sirnight head extras: parented to bone 107, weighted to bone 71).
        bone_idx = ir_mesh.parent_bone_index
        if bone_idx < len(bones) and bones[bone_idx].world_matrix:
            world_inv = Matrix(bones[bone_idx].world_matrix).inverted()
            export_vertices = [
                tuple(world_inv @ Vector(v)) for v in ir_mesh.vertices
            ]


    # Vertices are already in GC units — the pre-scale pass in compose_scene
    # converted the whole IRScene from meters to GC units once up front.
    pos_data, pos_buffer = _encode_float3_buffer(export_vertices)
    pos_desc = _make_vertex_desc(GX_VA_POS, GX_POS_XYZ, GX_F32, stride=12)
    pos_desc.raw_vertex_data = pos_buffer
    vertex_descs.append(pos_desc)
    vertex_buffers.append(pos_data)

    # Normals — per-loop, need to de-duplicate into indexed buffer
    if ir_mesh.normals:
        nrm_verts, nrm_indices, nrm_buffer = _encode_indexed_float3(ir_mesh.normals)
        nrm_desc = _make_vertex_desc(GX_VA_NRM, GX_NRM_XYZ, GX_F32, stride=12)
        nrm_desc.raw_vertex_data = nrm_buffer
        vertex_descs.append(nrm_desc)
        vertex_buffers.append(('normals', nrm_verts, nrm_indices))

    # UV layers — convert from Blender UV convention to GX convention.
    # Blender UV origin is bottom-left (V goes up), GX origin is top-left
    # (V goes down). Flip V when encoding to GX vertex buffers.
    for uv_i, uv_layer in enumerate(ir_mesh.uv_layers):
        flipped_uvs = [(u, 1.0 - v) for u, v in uv_layer.uvs]
        uv_verts, uv_indices, uv_buffer = _encode_indexed_float2(flipped_uvs)
        uv_idx = _parse_uv_index(uv_layer.name, uv_i)
        uv_desc = _make_vertex_desc(GX_VA_TEX0 + uv_idx, GX_TEX_ST, GX_F32, stride=8)
        uv_desc.raw_vertex_data = uv_buffer
        vertex_descs.append(uv_desc)
        vertex_buffers.append(('uv', uv_verts, uv_indices))

    # Color layers — only include if colors actually vary per vertex.
    # Uniform color layers (all identical values) are material-level defaults
    # that should not be encoded as vertex attributes.
    for color_layer in ir_mesh.color_layers:
        # Skip alpha-only layers (alpha is part of RGBA in the color layer)
        if 'alpha_' in color_layer.name:
            continue
        # Skip uniform color layers (no per-vertex variation)
        if color_layer.colors and all(c == color_layer.colors[0] for c in color_layer.colors):
            continue
        clr_attr = GX_VA_CLR0 if 'color_0' in color_layer.name else GX_VA_CLR1
        clr_verts, clr_indices, clr_buffer = _encode_indexed_rgba(color_layer.colors)
        clr_desc = _make_vertex_desc(clr_attr, 0, GX_RGBA8, stride=4)
        clr_desc.attribute_type = GX_INDEX16
        clr_desc.component_count = 0  # GX_CLR_RGBA
        clr_desc.raw_vertex_data = clr_buffer
        vertex_descs.append(clr_desc)
        vertex_buffers.append(('color', clr_verts, clr_indices))

    # HSDLib parity: normals and vertex colors are mutually exclusive per
    # PObject on GameCube. Verified across 8 shipped XD/Colo models
    # (215 PObjects total): zero carry both. Until we implement per-attribute
    # PObject splitting, warn so the user can decide whether to strip one
    # attribute in the source scene. See CLAUDE.md TODO.
    attrs = {d.attribute for d in vertex_descs}
    if GX_VA_NRM in attrs and (GX_VA_CLR0 in attrs or GX_VA_CLR1 in attrs):
        logger.warning("      pobj '%s': carries both NRM and CLR — zero game "
                       "PObjects do this; one attribute will likely be ignored "
                       "in-game", ir_mesh.name)

    # Determine cull flags (shared across all split PObjects)
    cull_flags = POBJ_CULLBACK
    if ir_mesh.cull_front:
        cull_flags |= POBJ_CULLFRONT
    if not ir_mesh.cull_back:
        cull_flags &= ~POBJ_CULLBACK

    # Split into multiple PObjects if envelope count exceeds GX's 10 matrix slots
    max_envelopes = 10
    if is_envelope and len(envelope_map['envelopes']) > max_envelopes:
        return _build_split_pobjs(
            ir_mesh, envelope_map, vertex_descs, vertex_buffers,
            joints, bone_name_to_index, cull_flags, logger)

    # Single PObject path (<=10 envelopes or non-envelope mesh)
    raw_dl = _encode_display_list(ir_mesh.faces, ir_mesh.vertices,
                                  vertex_descs, vertex_buffers)

    pobj = _make_pobj_node(vertex_descs, raw_dl, cull_flags)

    # Skinning
    if is_envelope:
        pobj.property = _build_envelope_lists(
            envelope_map, joints, bone_name_to_index)
        pobj.flags |= POBJ_ENVELOPE | 0x1  # bit 0 always set alongside ENVELOPE
    elif bw and bw.type == SkinType.SINGLE_BONE and bw.bone_name:
        # POBJ_SKIN ("singly-bound") — UNVERIFIED PATH. describe_blender
        # never produces SINGLE_BONE (always WEIGHTED), so this branch only
        # fires for IRs constructed directly (e.g. importer's POBJ_SKIN
        # path, which itself is never exercised by any of the 1127 surveyed
        # game-original models). The vertex inverse-transform above uses
        # parent_bone_index for round-trip symmetry with the importer, but
        # that mirrors a likely-incorrect importer convention — see the
        # matching note in importer/phases/describe/helpers/meshes.py.
        bone_idx = bone_name_to_index.get(bw.bone_name)
        if bone_idx is not None and bone_idx < len(joints):
            pobj.property = joints[bone_idx]
        else:
            pobj.property = None
    else:
        pobj.property = None

    # Log PObject details
    skin_type = 'ENVELOPE' if is_envelope else ('SKIN' if pobj.flags & POBJ_SKIN else 'RIGID')
    desc_summary = ', '.join(f'attr={d.attribute}' for d in vertex_descs)
    total_buf_bytes = sum(len(d.raw_vertex_data) for d in vertex_descs if hasattr(d, 'raw_vertex_data'))
    logger.debug("      pobj '%s': %d verts, %d faces, %d descs [%s], dl=%d bytes, bufs=%d bytes, skin=%s, flags=%#x",
                 ir_mesh.name, len(ir_mesh.vertices), len(ir_mesh.faces),
                 len(vertex_descs), desc_summary, len(raw_dl), total_buf_bytes,
                 skin_type, pobj.flags)

    return [pobj]


def _make_pobj_node(vertex_descs, raw_dl, cull_flags):
    """Create a PObject node with the given display list and cull flags."""
    vtx_list = VertexList(address=None, blender_obj=None)
    vtx_list.vertices = vertex_descs
    vtx_list.vertex_length = 24  # sizeof(Vertex) in binary: 7 fields

    pobj = PObject(address=None, blender_obj=None)
    pobj.name = None
    pobj.next = None
    pobj.vertex_list = vtx_list
    pobj.flags = cull_flags
    pobj.raw_display_list = raw_dl
    pobj.display_list_chunk_count = (len(raw_dl) + 31) // 32
    pobj.display_list_address = 0  # Will be set during writePrivateData
    pobj.sources = []
    pobj.face_lists = []
    pobj.normals = []
    pobj.property = None
    return pobj


def _build_split_pobjs(ir_mesh, envelope_map, vertex_descs, vertex_buffers,
                       joints, bone_name_to_index, cull_flags, logger):
    """Split an envelope mesh with >10 weight combos into multiple PObjects.

    The GX hardware has 10 position/normal matrix slots (PNMTXIDX 0..27
    in steps of 3). Each PObject's display list can reference at most 10
    envelopes. This function partitions the mesh's triangles into groups
    where each group uses ≤10 unique envelopes, then builds one PObject
    per group.

    Returns:
        list[PObject] — one per envelope group.
    """
    triangles, tri_loop_indices = _triangulate_faces(ir_mesh.faces)
    groups = _partition_triangles_by_envelope(
        triangles, tri_loop_indices, envelope_map)

    num_envs = len(envelope_map['envelopes'])
    logger.info("      splitting mesh '%s' (%d envelopes) into %d PObjects",
                ir_mesh.name, num_envs, len(groups))

    pobjs = []
    for group_idx, group in enumerate(groups):
        local_env_map = _build_split_envelope_map(
            envelope_map, group['envelope_indices'], group['triangles'])

        # Build local vertex_buffers with the split envelope map
        local_vbufs = []
        for desc, vbuf in zip(vertex_descs, vertex_buffers):
            if desc.attribute == GX_VA_PNMTXIDX:
                local_vbufs.append(('pnmtxidx', local_env_map))
            else:
                local_vbufs.append(vbuf)

        raw_dl = _encode_display_list(
            None, ir_mesh.vertices, vertex_descs, local_vbufs,
            pre_triangulated=(group['triangles'], group['tri_loop_indices']))

        pobj = _make_pobj_node(vertex_descs, raw_dl, cull_flags)
        pobj.property = _build_envelope_lists(
            local_env_map, joints, bone_name_to_index)
        pobj.flags |= POBJ_ENVELOPE | 0x1

        logger.debug("        group %d: %d tris, %d envelopes, dl=%d bytes",
                     group_idx, len(group['triangles']),
                     len(group['envelope_indices']), len(raw_dl))
        pobjs.append(pobj)

    return pobjs


# ---------------------------------------------------------------------------
# Envelope (WEIGHTED skinning) helpers
# ---------------------------------------------------------------------------

def _undeform_vertices(vertices, envelope_map, bones, bone_name_to_index,
                       parent_bone_index, logger):
    """Reverse the envelope deformation applied by the describe phase.

    The describe phase transforms vertices via:
        world_pos = (bone_world @ bone_IBM [@ coord]) @ bind_pos
    This reverses it by computing the same deformation matrices and
    inverting them, matching describe/meshes.py's _extract_envelope_weights.

    Consumes the same `envelope_map` that is written to disk so the stored
    envelope weights and the un-deform matrix agree vertex-by-vertex. Two
    vertices sharing an envelope must reverse the same blend; otherwise
    the runtime re-deforms them with the stored envelope and they land at
    the wrong world position.
    """
    try:
        from .....shared.Constants.hsd import JOBJ_SKELETON_ROOT
    except (ImportError, SystemError):
        from shared.Constants.hsd import JOBJ_SKELETON_ROOT

    vertex_to_env = envelope_map['vertex_to_env']
    env_combos = envelope_map['envelopes']

    # Compute envelope coordinate system (mirrors describe phase)
    coord = _envelope_coord_system(parent_bone_index, bones, JOBJ_SKELETON_ROOT)

    # Compute inverse deformation matrix per envelope
    inv_deform = []
    for weight_list in env_combos:
        zero = [[0] * 4 for _ in range(4)]
        matrix = Matrix(zero)

        for bone_name, weight in weight_list:
            bone_idx = bone_name_to_index.get(bone_name, 0)
            bone = bones[bone_idx]
            bone_world = Matrix(bone.world_matrix)
            bone_ibm = _get_invbind_matrix(bone_idx, bones)
            contrib = bone_world @ bone_ibm
            for i in range(4):
                for j in range(4):
                    matrix[i][j] += weight * contrib[i][j]

        if coord:
            matrix = matrix @ coord

        try:
            inv_deform.append(matrix.inverted())
        except (ValueError, ZeroDivisionError):
            inv_deform.append(Matrix([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]))

    # Apply inverse deformation to each vertex
    result = list(vertices)
    for vertex_idx, env_idx in vertex_to_env.items():
        if vertex_idx < len(result) and env_idx < len(inv_deform):
            old_pos = result[vertex_idx]
            new_pos = inv_deform[env_idx] @ Vector(old_pos)
            result[vertex_idx] = (new_pos[0], new_pos[1], new_pos[2])

    return result


def _get_invbind_matrix(bone_index, bones):
    """Walk up the bone hierarchy to find the nearest inverse bind matrix."""
    idx = bone_index
    while idx is not None:
        bone = bones[idx]
        if bone.inverse_bind_matrix:
            return Matrix(bone.inverse_bind_matrix)
        idx = bone.parent_index
    return Matrix([[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]])


def _find_skeleton_bone(bone_index, bones, _unused=None):
    """Walk up from `bone_index` to the nearest bone with SKELETON or
    SKELETON_ROOT flag. MUST mirror the importer's describe-side version
    at importer/phases/describe/helpers/meshes.py:_find_skeleton_bone — if
    the two disagree, the compose un-deform and import re-deform compute
    different `coord` matrices and rest-pose vertices round-trip wrong.
    """
    idx = bone_index
    while idx is not None:
        if bones[idx].flags & (JOBJ_SKELETON | JOBJ_SKELETON_ROOT):
            return idx
        idx = bones[idx].parent_index
    return None


def _envelope_coord_system(bone_index, bones, JOBJ_SKELETON_ROOT):
    """Compute envelope coordinate system matrix for a bone.

    Mirrors importer/phases/describe/helpers/meshes.py:_envelope_coord_system.
    """
    bone = bones[bone_index]
    if bone.flags & JOBJ_SKELETON_ROOT:
        return None

    skel_idx = _find_skeleton_bone(bone_index, bones, JOBJ_SKELETON_ROOT)
    if skel_idx is None:
        return None

    inv_bind = _get_invbind_matrix(bone_index, bones)
    bone_world = Matrix(bone.world_matrix)

    if skel_idx == bone_index:
        return inv_bind.inverted()
    elif bones[skel_idx].flags & JOBJ_SKELETON_ROOT:
        skel_world = Matrix(bones[skel_idx].world_matrix)
        return skel_world.inverted() @ bone_world
    else:
        skel_world = Matrix(bones[skel_idx].world_matrix)
        return (skel_world @ inv_bind).inverted() @ bone_world


def _canonicalize_weights(weight_list):
    """Renormalise a vertex's weight list.

    Single source of truth consumed by both `_build_envelope_map` (what is
    written to disk) and `_undeform_vertices` (what the export position
    reverses). If those two ever drift apart, vertices that collapse into a
    shared envelope get un-deformed by one blend matrix but re-deformed by
    a different one at runtime.

    Weight limiting and quantization are the prepare script's job (see
    scripts/prepare_for_export.py) so the viewport preview matches what
    ships to the .dat. Compose only renormalises against floating-point
    drift.

    Returns:
        (canonical_list, key) where canonical_list is the renormalised
        `[(bone_name, weight), ...]` (in the original order) and key is
        the hashable sorted form for dedup.
    """
    s = sum(w for _, w in weight_list)
    if abs(s - 1.0) > 0.001 and s > 0:
        weight_list = [(name, w / s) for name, w in weight_list]
    canonical = list(weight_list)
    key = tuple(sorted(canonical))
    return canonical, key


def _build_envelope_map(assignments, bone_name_to_index, logger=None):
    """Build a mapping from vertex indices to envelope indices.

    Groups vertices by their unique bone weight combination (after
    renormalisation). Each unique combination becomes one EnvelopeList
    entry whose weights are exactly what downstream un-deformation will
    reverse.

    Args:
        assignments: list[(vertex_idx, [(bone_name, weight), ...])]
        bone_name_to_index: dict mapping bone name → index
        logger: optional Logger for the summary line.

    Returns:
        dict with keys:
            'vertex_to_env': {vertex_idx: envelope_index}
            'envelopes': list of canonical [(bone_name, weight), ...] per unique combo
    """
    combo_to_env = {}
    envelopes = []
    vertex_to_env = {}
    normalised = 0

    for vertex_idx, weight_list in assignments:
        pre_sum = sum(w for _, w in weight_list)
        if abs(pre_sum - 1.0) > 0.001 and pre_sum > 0:
            normalised += 1
        canonical, key = _canonicalize_weights(weight_list)
        if key not in combo_to_env:
            combo_to_env[key] = len(envelopes)
            envelopes.append(canonical)
        vertex_to_env[vertex_idx] = combo_to_env[key]

    if normalised and logger is not None:
        logger.info("    Renormalised %d vertex envelope(s) that didn't sum to 1.0",
                    normalised)

    return {
        'vertex_to_env': vertex_to_env,
        'envelopes': envelopes,
    }


def _build_envelope_lists(envelope_map, joints, bone_name_to_index):
    """Build EnvelopeList node array from the envelope map.

    Returns:
        list[EnvelopeList] — the null-terminated pointer array for PObject.property.
    """
    env_lists = []
    for weight_list in envelope_map['envelopes']:
        env_list = EnvelopeList(address=None, blender_obj=None)
        env_list.envelopes = []
        for bone_name, weight in weight_list:
            env = Envelope(address=None, blender_obj=None)
            bone_idx = bone_name_to_index.get(bone_name)
            if bone_idx is not None and bone_idx < len(joints):
                env.joint = joints[bone_idx]
            else:
                env.joint = None
            env.weight = weight
            env_list.envelopes.append(env)
        env_lists.append(env_list)
    return env_lists


# ---------------------------------------------------------------------------
# Vertex buffer encoding
# ---------------------------------------------------------------------------

def _parse_uv_index(name, fallback):
    """Extract the UV texture index from a layer name.

    Handles importer names like 'uvtex_0' and Blender defaults like 'UVMap'.
    """
    if not name:
        return fallback
    match = re.search(r'(\d+)$', name)
    if match:
        return int(match.group(1))
    return fallback


def _make_vertex_desc(attribute, component_count, component_type, stride):
    """Create a Vertex descriptor node with the given GX parameters."""
    v = Vertex(address=None, blender_obj=None)
    v.attribute = attribute
    v.attribute_type = GX_INDEX16
    v.component_count = component_count
    v.component_type = component_type
    v.component_frac = 0
    v.stride = stride
    v.base_pointer = _alloc_base_pointer()
    v.raw_vertex_data = b''
    return v


def _encode_float3_buffer(vertices):
    """Encode a list of (x,y,z) tuples into a float32 vertex buffer.

    Returns:
        (vertex_list, raw_bytes) — the vertex data and packed buffer.
    """
    buf = bytearray()
    for v in vertices:
        buf.extend(pack_many('float', v[0], v[1], v[2]))
    return vertices, bytes(buf)


def _encode_indexed_float3(per_loop_data):
    """De-duplicate per-loop float3 data into an indexed buffer.

    Returns:
        (unique_verts, per_loop_indices, raw_bytes)
    """
    unique = []
    index_map = {}
    indices = []

    for val in per_loop_data:
        key = (round(val[0], 6), round(val[1], 6), round(val[2], 6))
        if key not in index_map:
            index_map[key] = len(unique)
            unique.append(val)
        indices.append(index_map[key])

    buf = bytearray()
    for v in unique:
        buf.extend(pack_many('float', v[0], v[1], v[2]))
    return unique, indices, bytes(buf)


def _encode_indexed_float2(per_loop_data):
    """De-duplicate per-loop float2 data into an indexed buffer.

    Returns:
        (unique_verts, per_loop_indices, raw_bytes)
    """
    unique = []
    index_map = {}
    indices = []

    for val in per_loop_data:
        key = (round(val[0], 6), round(val[1], 6))
        if key not in index_map:
            index_map[key] = len(unique)
            unique.append(val)
        indices.append(index_map[key])

    buf = bytearray()
    for v in unique:
        buf.extend(pack_many('float', v[0], v[1]))
    return unique, indices, bytes(buf)


def _encode_indexed_rgba(per_loop_data):
    """De-duplicate per-loop RGBA data into an indexed buffer.

    Colors are stored as RGBA8 (4 bytes per vertex).

    Returns:
        (unique_colors, per_loop_indices, raw_bytes)
    """
    unique = []
    index_map = {}
    indices = []

    for val in per_loop_data:
        r = min(255, max(0, int(val[0] * 255 + 0.5)))
        g = min(255, max(0, int(val[1] * 255 + 0.5)))
        b = min(255, max(0, int(val[2] * 255 + 0.5)))
        a = min(255, max(0, int(val[3] * 255 + 0.5)))
        key = (r, g, b, a)
        if key not in index_map:
            index_map[key] = len(unique)
            unique.append(val)
        indices.append(index_map[key])

    buf = bytearray()
    for val in unique:
        r = min(255, max(0, int(val[0] * 255 + 0.5)))
        g = min(255, max(0, int(val[1] * 255 + 0.5)))
        b = min(255, max(0, int(val[2] * 255 + 0.5)))
        a = min(255, max(0, int(val[3] * 255 + 0.5)))
        buf.extend(pack_many('uchar', r, g, b, a))
    return unique, indices, bytes(buf)


# ---------------------------------------------------------------------------
# Display list splitting (envelope overflow)
# ---------------------------------------------------------------------------

def _triangulate_faces(faces):
    """Convert polygon faces into triangles.

    Returns:
        (triangles, tri_loop_indices) — parallel lists of [v0, v1, v2]
        vertex indices and [l0, l1, l2] loop indices.
    """
    triangles = []
    tri_loop_indices = []
    loop_idx = 0

    for face in faces:
        base = loop_idx
        if len(face) == 3:
            triangles.append(face)
            tri_loop_indices.append([base, base + 1, base + 2])
        elif len(face) == 4:
            triangles.append([face[0], face[1], face[2]])
            tri_loop_indices.append([base, base + 1, base + 2])
            triangles.append([face[0], face[2], face[3]])
            tri_loop_indices.append([base, base + 2, base + 3])
        elif len(face) > 4:
            for i in range(1, len(face) - 1):
                triangles.append([face[0], face[i], face[i + 1]])
                tri_loop_indices.append([base, base + i, base + i + 1])
        loop_idx += len(face)

    return triangles, tri_loop_indices


def _partition_triangles_by_envelope(triangles, tri_loop_indices,
                                     envelope_map, max_envelopes=10):
    """Partition triangles into groups where each uses ≤max_envelopes.

    Uses greedy best-fit: each triangle is added to the group whose
    envelope set has the most overlap (smallest resulting union), or
    a new group is created if none can fit.

    Returns:
        list of dicts, each with:
            'triangles': list of [v0, v1, v2]
            'tri_loop_indices': list of [l0, l1, l2]
            'envelope_indices': sorted list of global envelope indices used
    """
    vtx_to_env = envelope_map['vertex_to_env']

    groups = []  # list of (env_set, triangles, tri_loop_indices)

    for tri_idx, tri in enumerate(triangles):
        tri_envs = {vtx_to_env.get(v, 0) for v in tri}

        # Find best-fit group: smallest union size that's still <= max
        best_group = None
        best_union_size = max_envelopes + 1
        for group in groups:
            union_size = len(group[0] | tri_envs)
            if union_size <= max_envelopes and union_size < best_union_size:
                best_group = group
                best_union_size = union_size

        if best_group is not None:
            best_group[0].update(tri_envs)
            best_group[1].append(tri)
            best_group[2].append(tri_loop_indices[tri_idx])
        else:
            groups.append((
                set(tri_envs),
                [tri],
                [tri_loop_indices[tri_idx]],
            ))

    return [
        {
            'triangles': g[1],
            'tri_loop_indices': g[2],
            'envelope_indices': sorted(g[0]),
        }
        for g in groups
    ]


def _build_split_envelope_map(global_envelope_map, group_envelope_indices,
                              group_triangles):
    """Build a local envelope map for one split group.

    Remaps global envelope indices to local 0-based indices and includes
    only the envelopes/vertices used by this group.

    Returns:
        dict with 'vertex_to_env' (local indices) and 'envelopes' (subset).
    """
    global_to_local = {g: l for l, g in enumerate(group_envelope_indices)}
    global_vtx_to_env = global_envelope_map['vertex_to_env']
    global_envelopes = global_envelope_map['envelopes']

    # Collect vertices used by this group's triangles
    group_verts = set()
    for tri in group_triangles:
        group_verts.update(tri)

    local_vtx_to_env = {}
    for v in group_verts:
        global_idx = global_vtx_to_env.get(v, 0)
        local_vtx_to_env[v] = global_to_local[global_idx]

    local_envelopes = [global_envelopes[g] for g in group_envelope_indices]

    return {
        'vertex_to_env': local_vtx_to_env,
        'envelopes': local_envelopes,
    }


# ---------------------------------------------------------------------------
# Display list encoding
# ---------------------------------------------------------------------------

def _encode_display_list(faces, vertices, vertex_descs, vertex_buffers,
                         pre_triangulated=None):
    """Encode faces into a display list.

    Emits GX_DRAW_QUADS for 4-vertex faces and GX_DRAW_TRIANGLES for
    triangles, so quads in the source mesh round-trip without being
    split into two triangles (which would double the loop count and
    perturb shading on flat-quad surfaces). n-gons (>4) are fan-
    triangulated into the GX_DRAW_TRIANGLES section.

    When `pre_triangulated` is provided, only GX_DRAW_TRIANGLES is
    emitted — the envelope splitter pre-triangulates so it can pack
    triangles into ≤10-envelope groups, and we honour that directly.

    Args:
        faces: list[list[int]] — per-face vertex index lists (tris, quads,
               or n-gons). Ignored when pre_triangulated is provided.
        vertices: list[tuple] — position vertices (for index range).
        vertex_descs: list[Vertex] — vertex attribute descriptors.
        vertex_buffers: list — parallel to vertex_descs.
        pre_triangulated: optional (triangles, tri_loop_indices) tuple.
               When provided, faces is ignored and these are used directly.

    Returns:
        bytes — the raw display list, padded to 32-byte alignment.
    """
    if pre_triangulated:
        tris, tri_loops = pre_triangulated
        # Split-PObj path: emit one GX_DRAW_TRIANGLES block directly.
        ordered_blocks = [('tri', tris, tri_loops)] if tris else []
    else:
        ordered_blocks = _group_faces_for_display_list(faces)

    if not ordered_blocks:
        return b'\x00' * 32

    buf = bytearray()

    # Emit blocks in face order — contiguous runs of same primitive type
    # stay batched so mixed-primitive meshes (tri, quad, tri) preserve
    # their per-loop UV/normal/color buffer order through round-trip.
    for kind, prims, loop_idx_lists in ordered_blocks:
        if kind == 'quad':
            buf.append(GX_DRAW_QUADS)
            buf.extend(pack('ushort', len(prims) * 4))
            swap = [3, 2, 1, 0]
        else:
            buf.append(GX_DRAW_TRIANGLES)
            buf.extend(pack('ushort', len(prims) * 3))
            swap = [0, 2, 1]
        for p_idx, prim in enumerate(prims):
            lidxs = loop_idx_lists[p_idx]
            for vi in swap:
                _write_dl_vertex(buf, prim[vi], lidxs[vi],
                                 vertex_descs, vertex_buffers)

    # Pad to 32-byte alignment
    while len(buf) % 32 != 0:
        buf.append(0x00)

    return bytes(buf)


def _group_faces_for_display_list(faces):
    """Group faces into contiguous runs of same-primitive blocks.

    Returns a list of (kind, prims, loop_idx_lists) tuples where:
    - kind is 'quad' (4-verts) or 'tri' (3-verts or fan-triangulated n-gons)
    - prims is list[list[int]] of vertex indices per primitive
    - loop_idx_lists is list[list[int]] of loop indices per primitive

    Order of the input faces list is preserved. n-gons (>4) are fan-
    triangulated inline and joined into the surrounding triangle run.
    """
    blocks = []
    current = None
    loop_idx = 0

    def _append(kind, prim, lidxs):
        nonlocal current
        if current is None or current[0] != kind:
            current = (kind, [], [])
            blocks.append(current)
        current[1].append(prim)
        current[2].append(lidxs)

    for face in faces:
        base = loop_idx
        n = len(face)
        if n == 3:
            _append('tri', list(face), [base, base + 1, base + 2])
        elif n == 4:
            _append('quad', list(face), [base, base + 1, base + 2, base + 3])
        elif n > 4:
            for i in range(1, n - 1):
                _append('tri', [face[0], face[i], face[i + 1]],
                        [base, base + i, base + i + 1])
        loop_idx += n

    return blocks


def _write_dl_vertex(buf, pos_index, loop_index, vertex_descs, vertex_buffers):
    """Write one vertex's attribute indices into the display list buffer."""
    for desc_idx, desc in enumerate(vertex_descs):
        vbuf = vertex_buffers[desc_idx]

        if desc.attribute == GX_VA_PNMTXIDX:
            # Envelope index: vertex_idx → env_idx * 3
            # GX hardware has 10 matrix slots (indices 0,3,...,27)
            _, env_map = vbuf
            env_idx = env_map['vertex_to_env'].get(pos_index, 0)
            assert env_idx < 10, (
                f"PNMTXIDX {env_idx} >= 10: mesh needs display list "
                f"splitting (should have been handled by _build_split_pobjs)")
            buf.append(env_idx * 3)
        elif desc.attribute == GX_VA_POS:
            buf.extend(pack('ushort', pos_index))
        elif isinstance(vbuf, tuple) and len(vbuf) == 3:
            # Per-loop attribute (normals, UVs, colors)
            _, _, per_loop_indices = vbuf
            if loop_index < len(per_loop_indices):
                idx = per_loop_indices[loop_index]
            else:
                idx = 0
            buf.extend(pack('ushort', idx))
        else:
            buf.extend(pack('ushort', pos_index))


