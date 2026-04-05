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
        GX_DRAW_TRIANGLES,
    )
    from .....shared.Constants.hsd import (
        POBJ_CULLFRONT, POBJ_CULLBACK, POBJ_SKIN, POBJ_ENVELOPE,
        JOBJ_HIDDEN,
    )
    from .....shared.IR.enums import SkinType
    from .....shared.helpers.binary import pack, pack_many
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
        GX_DRAW_TRIANGLES,
    )
    from shared.Constants.hsd import (
        POBJ_CULLFRONT, POBJ_CULLBACK, POBJ_SKIN, POBJ_ENVELOPE,
        JOBJ_HIDDEN,
    )
    from shared.IR.enums import SkinType
    from shared.helpers.binary import pack, pack_many
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
                pobj = _build_pobj(ir_mesh, joints, bones, bone_name_to_index, logger)
                if pobj is not None:
                    pobjs.append(pobj)

            if not pobjs:
                continue

            # Chain PObjects via .next under one DObject
            for i in range(len(pobjs) - 1):
                pobjs[i].next = pobjs[i + 1]

            mesh_node = Mesh(address=None, blender_obj=None)
            mesh_node.name = None
            mesh_node.next = None
            mesh_node.mobject = compose_material(ir_material, logger=logger)
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
    """Build a PObject node from an IRMesh.

    Creates vertex descriptors, encodes vertex buffer data, and builds
    a GX display list for the geometry.

    Returns:
        PObject node, or None if the mesh has no geometry.
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
        envelope_map = _build_envelope_map(bw.assignments, bone_name_to_index)
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

    # Position — always present
    pos_data, pos_buffer = _encode_float3_buffer(ir_mesh.vertices)
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

    # Build the display list
    raw_dl = _encode_display_list(ir_mesh.faces, ir_mesh.vertices, vertex_descs, vertex_buffers)

    # Create VertexList
    vtx_list = VertexList(address=None, blender_obj=None)
    vtx_list.vertices = vertex_descs
    vtx_list.vertex_length = 24  # sizeof(Vertex) in binary: 7 fields

    # Create PObject
    pobj = PObject(address=None, blender_obj=None)
    pobj.name = None
    pobj.next = None
    pobj.vertex_list = vtx_list
    pobj.flags = 0
    pobj.raw_display_list = raw_dl
    pobj.display_list_chunk_count = (len(raw_dl) + 31) // 32
    pobj.display_list_address = 0  # Will be set during writePrivateData
    pobj.sources = []
    pobj.face_lists = []
    pobj.normals = []

    # Cull flags — POBJ_CULLBACK is the default in HSD (backface culling on)
    pobj.flags |= POBJ_CULLBACK
    if ir_mesh.cull_front:
        pobj.flags |= POBJ_CULLFRONT
    if not ir_mesh.cull_back:
        pobj.flags &= ~POBJ_CULLBACK

    # Skinning
    if is_envelope:
        pobj.property = _build_envelope_lists(
            envelope_map, joints, bone_name_to_index)
        pobj.flags |= POBJ_ENVELOPE | 0x1  # bit 0 always set alongside ENVELOPE
    elif bw and bw.type == SkinType.SINGLE_BONE and bw.bone_name:
        bone_idx = bone_name_to_index.get(bw.bone_name)
        if bone_idx is not None and bone_idx < len(joints):
            # Set SKIN property — the Joint reference tells the game which
            # bone deforms this mesh. For self-referencing (bone == parent),
            # the mesh vertices are already positioned by the Joint hierarchy.
            pobj.property = joints[bone_idx]
            # POBJ_SKIN is 0x0 (default type field value), no flag to set
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

    return pobj


# ---------------------------------------------------------------------------
# Envelope (WEIGHTED skinning) helpers
# ---------------------------------------------------------------------------

def _build_envelope_map(assignments, bone_name_to_index):
    """Build a mapping from vertex indices to envelope indices.

    Groups vertices by their unique bone weight combination. Each unique
    combination becomes one EnvelopeList entry.

    Args:
        assignments: list[(vertex_idx, [(bone_name, weight), ...])]
        bone_name_to_index: dict mapping bone name → index

    Returns:
        dict with keys:
            'vertex_to_env': {vertex_idx: envelope_index}
            'envelopes': list of [(bone_name, weight), ...] per unique combo
    """
    combo_to_env = {}  # frozenset of (bone_name, weight) → env index
    envelopes = []
    vertex_to_env = {}

    for vertex_idx, weight_list in assignments:
        # Normalize: sort by bone name for consistent keys
        key = tuple(sorted((name, round(w, 6)) for name, w in weight_list))
        if key not in combo_to_env:
            combo_to_env[key] = len(envelopes)
            envelopes.append(weight_list)
        vertex_to_env[vertex_idx] = combo_to_env[key]

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
# Display list encoding
# ---------------------------------------------------------------------------

def _encode_display_list(faces, vertices, vertex_descs, vertex_buffers):
    """Encode faces into a GX_DRAW_TRIANGLES display list.

    The display list encodes triangulated faces. Each vertex in the DL
    contains one index per vertex descriptor (position, normal, UV, etc.).

    Args:
        faces: list[list[int]] — per-face vertex index lists (may be quads).
        vertices: list[tuple] — position vertices (for index range).
        vertex_descs: list[Vertex] — vertex attribute descriptors.
        vertex_buffers: list — parallel to vertex_descs.

    Returns:
        bytes — the raw display list, padded to 32-byte alignment.
    """
    # Triangulate faces (split quads into two triangles)
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

    if not triangles:
        return b'\x00' * 32

    vertex_count = len(triangles) * 3

    buf = bytearray()

    # Opcode: GX_DRAW_TRIANGLES
    buf.append(GX_DRAW_TRIANGLES)
    # Vertex count (ushort)
    buf.extend(pack('ushort', vertex_count))

    # Write vertex indices with GX winding (swap indices 1↔2 to convert
    # Blender CCW → GX CW). The parser's GX_DRAW_TRIANGLES handler will
    # swap them back to produce CCW faces on re-import.
    for tri_idx, tri in enumerate(triangles):
        loop_idxs = tri_loop_indices[tri_idx]
        for vi in [0, 2, 1]:
            pos_index = tri[vi]
            loop_index = loop_idxs[vi]

            for desc_idx, desc in enumerate(vertex_descs):
                vbuf = vertex_buffers[desc_idx]

                if desc.attribute == GX_VA_PNMTXIDX:
                    # Envelope index: vertex_idx → env_idx * 3
                    _, env_map = vbuf
                    env_idx = env_map['vertex_to_env'].get(pos_index, 0)
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

    # Pad to 32-byte alignment
    while len(buf) % 32 != 0:
        buf.append(0x00)

    return bytes(buf)
