"""Compose IRMesh list into Mesh → PObject → VertexList → Vertex node chains.

Reverses importer/phases/describe/helpers/meshes.py:describe_meshes().
Takes IRMesh dataclasses and reconstructs the SysDolphin node tree
structure with encoded vertex buffers and GX display lists.
"""
import struct
from collections import defaultdict

try:
    from ......shared.Nodes.Classes.Mesh.Mesh import Mesh
    from ......shared.Nodes.Classes.Mesh.PObject import PObject
    from ......shared.Nodes.Classes.Mesh.VertexList import VertexList
    from ......shared.Nodes.Classes.Mesh.Vertex import Vertex
    from ......shared.Constants.gx import (
        GX_VA_POS, GX_VA_NRM, GX_VA_CLR0, GX_VA_CLR1,
        GX_VA_TEX0,
        GX_INDEX16, GX_F32, GX_RGBA8,
        GX_POS_XYZ, GX_NRM_XYZ, GX_TEX_ST,
        GX_DRAW_TRIANGLES, GX_NOP,
    )
    from ......shared.Constants.hsd import (
        POBJ_CULLFRONT, POBJ_CULLBACK, POBJ_SKIN,
    )
    from ......shared.IR.enums import SkinType
    from ......shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Mesh.Mesh import Mesh
    from shared.Nodes.Classes.Mesh.PObject import PObject
    from shared.Nodes.Classes.Mesh.VertexList import VertexList
    from shared.Nodes.Classes.Mesh.Vertex import Vertex
    from shared.Constants.gx import (
        GX_VA_POS, GX_VA_NRM, GX_VA_CLR0, GX_VA_CLR1,
        GX_VA_TEX0,
        GX_INDEX16, GX_F32, GX_RGBA8,
        GX_POS_XYZ, GX_NRM_XYZ, GX_TEX_ST,
        GX_DRAW_TRIANGLES, GX_NOP,
    )
    from shared.Constants.hsd import (
        POBJ_CULLFRONT, POBJ_CULLBACK, POBJ_SKIN,
    )
    from shared.IR.enums import SkinType
    from shared.helpers.logger import StubLogger


def compose_meshes(meshes, joints, bones, logger=StubLogger()):
    """Convert IRMesh list into Mesh node chains attached to Joints.

    Groups meshes by parent_bone_index, creates one Mesh → PObject chain
    per bone, and sets joint.property to the head Mesh node.

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

    # Group meshes by parent bone
    meshes_by_bone = defaultdict(list)
    for ir_mesh in meshes:
        bone_idx = ir_mesh.parent_bone_index
        if bone_idx < len(joints):
            meshes_by_bone[bone_idx].append(ir_mesh)

    bone_name_to_index = {bone.name: i for i, bone in enumerate(bones)}

    for bone_idx, ir_meshes in meshes_by_bone.items():
        mesh_nodes = []
        for ir_mesh in ir_meshes:
            pobj = _build_pobj(ir_mesh, joints, bones, bone_name_to_index, logger)
            if pobj is None:
                continue

            mesh_node = Mesh(address=None, blender_obj=None)
            mesh_node.name = None
            mesh_node.next = None
            mesh_node.mobject = None  # Material compose not yet implemented
            mesh_node.pobject = pobj
            mesh_nodes.append(mesh_node)

        if not mesh_nodes:
            continue

        # Link mesh nodes into a linked list via .next
        for i in range(len(mesh_nodes) - 1):
            mesh_nodes[i].next = mesh_nodes[i + 1]

        # Attach to joint
        joints[bone_idx].property = mesh_nodes[0]

    total_meshes = sum(len(ml) for ml in meshes_by_bone.values())
    logger.info("Composed %d meshes across %d bones", total_meshes, len(meshes_by_bone))


def _build_pobj(ir_mesh, joints, bones, bone_name_to_index, logger):
    """Build a PObject node from an IRMesh.

    Creates vertex descriptors, encodes vertex buffer data, and builds
    a GX display list for the geometry.

    Returns:
        PObject node, or None if the mesh has no geometry.
    """
    if not ir_mesh.vertices or not ir_mesh.faces:
        return None

    # Build vertex descriptors and encode vertex/display list data
    vertex_descs = []
    vertex_buffers = []

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

    # UV layers
    for uv_i, uv_layer in enumerate(ir_mesh.uv_layers):
        uv_verts, uv_indices, uv_buffer = _encode_indexed_float2(uv_layer.uvs)
        uv_idx = _parse_uv_index(uv_layer.name, uv_i)
        uv_desc = _make_vertex_desc(GX_VA_TEX0 + uv_idx, GX_TEX_ST, GX_F32, stride=8)
        uv_desc.raw_vertex_data = uv_buffer
        vertex_descs.append(uv_desc)
        vertex_buffers.append(('uv', uv_verts, uv_indices))

    # Color layers
    for color_layer in ir_mesh.color_layers:
        clr_attr = GX_VA_CLR0 if 'color_0' in color_layer.name or 'alpha' not in color_layer.name else GX_VA_CLR1
        # Skip alpha-only layers (they're baked into the color layer on import)
        if 'alpha_' in color_layer.name:
            continue
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

    # Cull flags
    if ir_mesh.cull_front:
        pobj.flags |= POBJ_CULLFRONT
    if ir_mesh.cull_back:
        pobj.flags |= POBJ_CULLBACK

    # Skinning
    bw = ir_mesh.bone_weights
    if bw and bw.type == SkinType.SINGLE_BONE and bw.bone_name:
        bone_idx = bone_name_to_index.get(bw.bone_name)
        if bone_idx is not None and bone_idx < len(joints):
            pobj.property = joints[bone_idx]
            pobj.flags |= POBJ_SKIN
        else:
            pobj.property = None
    else:
        pobj.property = None

    return pobj


# ---------------------------------------------------------------------------
# Vertex buffer encoding
# ---------------------------------------------------------------------------

def _parse_uv_index(name, fallback):
    """Extract the UV texture index from a layer name.

    Handles importer names like 'uvtex_0' and Blender defaults like 'UVMap'.
    """
    if not name:
        return fallback
    # Try extracting trailing digits
    import re
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
    v.base_pointer = 0  # Will be set during write
    v.raw_vertex_data = b''
    return v


def _encode_float3_buffer(vertices):
    """Encode a list of (x,y,z) tuples into a float32 vertex buffer.

    Returns:
        (vertex_list, raw_bytes) — the vertex data and packed buffer.
    """
    buf = bytearray()
    for v in vertices:
        buf.extend(struct.pack('>fff', v[0], v[1], v[2]))
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
        buf.extend(struct.pack('>fff', v[0], v[1], v[2]))
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
        buf.extend(struct.pack('>ff', v[0], v[1]))
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
        buf.extend(struct.pack('>BBBB', r, g, b, a))
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
        vertex_buffers: list — parallel to vertex_descs; either
            (vertex_list, raw_bytes) for position, or
            ('type', unique_verts, per_loop_indices) for per-loop attributes.

    Returns:
        bytes — the raw display list, padded to 32-byte alignment.
    """
    # Triangulate faces (split quads into two triangles)
    triangles = []
    for face in faces:
        if len(face) == 3:
            triangles.append(face)
        elif len(face) == 4:
            triangles.append([face[0], face[1], face[2]])
            triangles.append([face[0], face[2], face[3]])
        elif len(face) > 4:
            # Fan triangulation
            for i in range(1, len(face) - 1):
                triangles.append([face[0], face[i], face[i + 1]])

    if not triangles:
        return b'\x00' * 32

    # Build a loop-index mapping: for each face, for each vertex in the face,
    # track which loop index it corresponds to (for per-loop attributes like
    # normals, UVs, colors).
    loop_idx = 0
    face_loop_starts = []
    for face in faces:
        face_loop_starts.append(loop_idx)
        loop_idx += len(face)

    # Build per-triangle loop indices
    tri_loop_indices = []
    face_offset = 0
    for face in faces:
        base = face_loop_starts[face_offset]
        if len(face) == 3:
            tri_loop_indices.append([base, base + 1, base + 2])
        elif len(face) == 4:
            tri_loop_indices.append([base, base + 1, base + 2])
            tri_loop_indices.append([base, base + 2, base + 3])
        elif len(face) > 4:
            for i in range(1, len(face) - 1):
                tri_loop_indices.append([base, base + i, base + i + 1])
        face_offset += 1

    vertex_count = len(triangles) * 3

    # Compute stride (bytes per vertex in DL)
    stride_per_vertex = 0
    for desc in vertex_descs:
        if desc.attribute_type == GX_INDEX16:
            stride_per_vertex += 2
        else:
            stride_per_vertex += 1  # GX_INDEX8

    buf = bytearray()

    # Opcode: GX_DRAW_TRIANGLES
    buf.append(GX_DRAW_TRIANGLES)
    # Vertex count (ushort)
    buf.extend(struct.pack('>H', vertex_count))

    # Write vertex indices — note: the GX convention for triangles reverses
    # winding order (v0, v2, v1) compared to the IR (v0, v1, v2).
    for tri_idx, tri in enumerate(triangles):
        loop_idxs = tri_loop_indices[tri_idx]
        # GX winding: v0, v2, v1
        for vi in [0, 2, 1]:
            pos_index = tri[vi]
            loop_index = loop_idxs[vi]

            for desc_idx, desc in enumerate(vertex_descs):
                vbuf = vertex_buffers[desc_idx]

                if desc.attribute == GX_VA_POS:
                    # Position: index directly into vertex list
                    idx = pos_index
                elif isinstance(vbuf, tuple) and len(vbuf) == 3:
                    # Per-loop attribute (normals, UVs, colors): use loop index
                    _, _, per_loop_indices = vbuf
                    if loop_index < len(per_loop_indices):
                        idx = per_loop_indices[loop_index]
                    else:
                        idx = 0
                else:
                    idx = pos_index

                buf.extend(struct.pack('>H', idx))

    # Pad to 32-byte alignment
    while len(buf) % 32 != 0:
        buf.append(0x00)

    return bytes(buf)
