"""End-to-end: compose emits triangle strips that round-trip through the
importer's display-list decode.

Phase 1 (test_stripify.py) validated the grouping algorithm on abstract
tokens. These tests drive the real `_encode_display_list` and decode its
emitted bytes with the exact opcode semantics of
`shared/Nodes/Classes/Mesh/PObject.py::read_geometry`, so they catch any
integration error — wrong winding, wrong strip layout, dropped/duplicated
faces, or strips welding across attribute seams.
"""
import struct
from collections import Counter

from shared.Constants.gx import (
    GX_DRAW_TRIANGLES, GX_DRAW_QUADS, GX_DRAW_TRIANGLE_STRIP,
    GX_NOP, GX_OPCODE_MASK,
    GX_VA_POS, GX_VA_NRM, GX_POS_XYZ, GX_NRM_XYZ, GX_F32,
)
from exporter.phases.compose.helpers.meshes import (
    _encode_display_list, _make_vertex_desc,
)


# ---------------------------------------------------------------------------
# Display-list decoder — mirrors PObject.read_geometry (lines 196-251),
# extracting the POS index from each vertex record by stride/offset.
# ---------------------------------------------------------------------------

def _decode_dl(dl, stride=2, pos_offset=0):
    faces = []
    off = 0
    n = len(dl)
    while off < n:
        opcode = dl[off] & GX_OPCODE_MASK
        off += 1
        if opcode == GX_NOP:          # padding / terminator
            break
        count = struct.unpack('>H', dl[off:off + 2])[0]
        off += 2
        verts_start = off
        idxs = []
        for v in range(count):
            p = verts_start + v * stride + pos_offset
            idxs.append(struct.unpack('>H', dl[p:p + 2])[0])
        off = verts_start + count * stride

        if opcode == GX_DRAW_QUADS:
            for i in range(count // 4):
                b = i * 4
                faces.append((idxs[b + 3], idxs[b + 2], idxs[b + 1], idxs[b + 0]))
        elif opcode == GX_DRAW_TRIANGLES:
            for i in range(count // 3):
                b = i * 3
                faces.append((idxs[b + 0], idxs[b + 2], idxs[b + 1]))
        elif opcode == GX_DRAW_TRIANGLE_STRIP:
            for i in range(count - 2):
                if i % 2 == 0:
                    faces.append((idxs[i + 1], idxs[i + 0], idxs[i + 2]))
                else:
                    faces.append((idxs[i + 0], idxs[i + 1], idxs[i + 2]))
    return faces


def _canon(face):
    """Cyclic-rotation canonical form (winding-preserving)."""
    i = face.index(min(face))
    return tuple(face[(i + k) % len(face)] for k in range(len(face)))


def _grid_faces(cols, rows):
    """cols x rows quad grid, each quad split into two CCW triangles, fully
    welded (shared vertex ids) so strips can run."""
    def vid(x, y):
        return y * (cols + 1) + x

    faces = []
    for y in range(rows):
        for x in range(cols):
            a, b = vid(x, y), vid(x + 1, y)
            c, d = vid(x + 1, y + 1), vid(x, y + 1)
            faces.append([a, b, c])
            faces.append([a, c, d])
    return faces


def _pos_only_descs():
    desc = _make_vertex_desc(GX_VA_POS, GX_POS_XYZ, GX_F32, stride=12)
    return [desc], [None]


# ---------------------------------------------------------------------------
# Geometry round-trip
# ---------------------------------------------------------------------------

def test_grid_roundtrips_through_decode():
    faces = _grid_faces(4, 4)
    descs, bufs = _pos_only_descs()
    n_verts = max(v for f in faces for v in f) + 1
    dl = _encode_display_list(faces, [(0, 0, 0)] * n_verts, descs, bufs)

    decoded = _decode_dl(dl)
    assert Counter(_canon(f) for f in decoded) == \
        Counter(_canon(tuple(f)) for f in faces)
    # Strips actually appeared (the whole point).
    assert GX_DRAW_TRIANGLE_STRIP in dl


def test_single_triangle_stays_triangles():
    faces = [[0, 1, 2]]
    descs, bufs = _pos_only_descs()
    dl = _encode_display_list(faces, [(0, 0, 0)] * 3, descs, bufs)
    assert dl[0] == GX_DRAW_TRIANGLES
    assert GX_DRAW_TRIANGLE_STRIP not in dl
    assert _decode_dl(dl) == [(0, 1, 2)]


def test_two_adjacent_triangles_become_a_strip():
    faces = [[0, 1, 2], [0, 2, 3]]      # share edge 0-2
    descs, bufs = _pos_only_descs()
    dl = _encode_display_list(faces, [(0, 0, 0)] * 4, descs, bufs)
    assert dl[0] == GX_DRAW_TRIANGLE_STRIP
    assert struct.unpack('>H', dl[1:3])[0] == 4   # 2 tris -> 4 strip verts
    decoded = _decode_dl(dl)
    assert Counter(_canon(tuple(f)) for f in decoded) == \
        Counter(_canon(tuple(f)) for f in faces)


def test_mixed_quad_and_triangles_roundtrip():
    # quad, then a strippable triangle pair.
    faces = [[0, 1, 2, 3], [4, 5, 6], [4, 6, 7]]
    descs, bufs = _pos_only_descs()
    dl = _encode_display_list(faces, [(0, 0, 0)] * 8, descs, bufs)
    decoded = _decode_dl(dl)
    assert Counter(_canon(tuple(f)) for f in decoded) == \
        Counter(_canon(tuple(f)) for f in faces)
    assert GX_DRAW_QUADS in dl


# ---------------------------------------------------------------------------
# Attribute-seam handling (POS + per-loop NRM): the strip must break where a
# shared position carries a different normal index on each side.
# ---------------------------------------------------------------------------

def _pos_nrm_descs(per_loop_normal_indices):
    pos = _make_vertex_desc(GX_VA_POS, GX_POS_XYZ, GX_F32, stride=12)
    nrm = _make_vertex_desc(GX_VA_NRM, GX_NRM_XYZ, GX_F32, stride=12)
    # POS uses pos_index; NRM is a per-loop buffer (3-tuple -> per-loop branch).
    return [pos, nrm], [None, (None, None, per_loop_normal_indices)]


def test_seam_breaks_strip_with_per_loop_normals():
    # Two triangles share positions 0 and 2 but with DIFFERENT normals there.
    # Loops: face0 [0,1,2] -> 0,1,2 ; face1 [0,2,3] -> 3,4,5.
    # pos0: loop0 vs loop3 ; pos2: loop2 vs loop4 — make them differ.
    faces = [[0, 1, 2], [0, 2, 3]]
    per_loop = [10, 11, 12, 99, 98, 13]   # loop3/loop4 differ from loop0/loop2
    descs, bufs = _pos_nrm_descs(per_loop)
    dl = _encode_display_list(faces, [(0, 0, 0)] * 4, descs, bufs)
    # No strip — the seam forces two loose triangles.
    assert GX_DRAW_TRIANGLE_STRIP not in dl
    assert dl[0] == GX_DRAW_TRIANGLES
    decoded = _decode_dl(dl, stride=4, pos_offset=0)
    assert Counter(_canon(tuple(f)) for f in decoded) == \
        Counter(_canon(tuple(f)) for f in faces)


def test_matching_normals_allow_strip():
    # Same geometry, but shared-vertex normals MATCH across the seam edge, so
    # the pair welds into a strip.
    faces = [[0, 1, 2], [0, 2, 3]]
    # pos0: loop0==loop3 ; pos2: loop2==loop4.
    per_loop = [10, 11, 12, 10, 12, 13]
    descs, bufs = _pos_nrm_descs(per_loop)
    dl = _encode_display_list(faces, [(0, 0, 0)] * 4, descs, bufs)
    assert dl[0] == GX_DRAW_TRIANGLE_STRIP
    decoded = _decode_dl(dl, stride=4, pos_offset=0)
    assert Counter(_canon(tuple(f)) for f in decoded) == \
        Counter(_canon(tuple(f)) for f in faces)
