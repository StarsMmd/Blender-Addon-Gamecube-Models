"""Regression: compose must emit GX_DRAW_QUADS for 4-vertex faces.

Previously every face was triangulated into two GX_DRAW_TRIANGLES entries,
which:
- doubled the per-loop UV/normal/color buffer length on re-import
  (a quad's 4 loops became 6)
- perturbed specular shading on flat-quad surfaces by introducing a
  diagonal seam — observed as yellow strips on sirnight's dress pleats
- broke bit-level round-trip for mixed tri/quad meshes

The parser in shared/Nodes/Classes/Mesh/PObject.py handles both
GX_DRAW_QUADS (0x80) and GX_DRAW_TRIANGLES (0x90); the compose side
now mirrors the source mesh's primitive mix.
"""
from shared.Constants.gx import GX_DRAW_QUADS, GX_DRAW_TRIANGLES
from exporter.phases.compose.helpers.meshes import (
    _group_faces_for_display_list,
)


def test_pure_triangles_one_tri_block():
    faces = [[0, 1, 2], [3, 4, 5]]
    blocks = _group_faces_for_display_list(faces)
    assert len(blocks) == 1
    kind, prims, loops = blocks[0]
    assert kind == 'tri'
    assert prims == [[0, 1, 2], [3, 4, 5]]
    assert loops == [[0, 1, 2], [3, 4, 5]]


def test_pure_quads_one_quad_block():
    faces = [[0, 1, 2, 3], [4, 5, 6, 7]]
    blocks = _group_faces_for_display_list(faces)
    assert len(blocks) == 1
    kind, prims, loops = blocks[0]
    assert kind == 'quad'
    assert prims == [[0, 1, 2, 3], [4, 5, 6, 7]]
    # Loop indices are monotonic across the original faces list —
    # quad 0 owns loops 0-3, quad 1 owns loops 4-7.
    assert loops == [[0, 1, 2, 3], [4, 5, 6, 7]]


def test_mixed_tri_quad_preserves_face_order():
    # tri → quad → tri: three separate blocks keep the source order.
    faces = [[0, 1, 2], [3, 4, 5, 6], [7, 8, 9]]
    blocks = _group_faces_for_display_list(faces)
    assert [b[0] for b in blocks] == ['tri', 'quad', 'tri']
    # Loop indices step through the original per-loop buffer:
    # tri 0 = loops 0-2, quad = loops 3-6, tri 1 = loops 7-9.
    assert blocks[0][2] == [[0, 1, 2]]
    assert blocks[1][2] == [[3, 4, 5, 6]]
    assert blocks[2][2] == [[7, 8, 9]]


def test_contiguous_same_kind_batched_into_single_block():
    # Two triangles in a row share one GX_DRAW_TRIANGLES block; the quad
    # that follows starts a new GX_DRAW_QUADS block.
    faces = [[0, 1, 2], [3, 4, 5], [6, 7, 8, 9]]
    blocks = _group_faces_for_display_list(faces)
    assert [b[0] for b in blocks] == ['tri', 'quad']
    assert blocks[0][1] == [[0, 1, 2], [3, 4, 5]]
    assert blocks[1][1] == [[6, 7, 8, 9]]


def test_ngon_fan_triangulated_into_tri_block():
    # A 5-vertex face fans into 3 triangles, all in the triangle block.
    faces = [[0, 1, 2, 3, 4]]
    blocks = _group_faces_for_display_list(faces)
    assert len(blocks) == 1
    kind, prims, loops = blocks[0]
    assert kind == 'tri'
    assert prims == [[0, 1, 2], [0, 2, 3], [0, 3, 4]]
    # Loop indices reference the original 5-loop face layout.
    assert loops == [[0, 1, 2], [0, 2, 3], [0, 3, 4]]


def test_empty_faces_returns_empty_blocks():
    assert _group_faces_for_display_list([]) == []


def test_display_list_emits_quad_opcode_when_mesh_has_quads():
    from exporter.phases.compose.helpers.meshes import _encode_display_list
    from shared.Constants.gx import GX_VA_POS, GX_POS_XYZ, GX_F32
    from exporter.phases.compose.helpers.meshes import _make_vertex_desc

    # Minimal descriptor list: just positions, so _write_dl_vertex emits
    # two bytes (ushort) per vertex.
    pos_desc = _make_vertex_desc(GX_VA_POS, GX_POS_XYZ, GX_F32, stride=12)
    vertex_descs = [pos_desc]
    vertex_buffers = [None]  # POS uses pos_index directly

    # One quad + one triangle — verifies both opcodes appear.
    faces = [[0, 1, 2, 3], [4, 5, 6]]
    dl = _encode_display_list(faces, vertices=[(0, 0, 0)] * 7,
                              vertex_descs=vertex_descs,
                              vertex_buffers=vertex_buffers)
    # The DL contains the quad block first, then triangle block.
    assert dl[0] == GX_DRAW_QUADS
    # ushort count = 4 vertices (big-endian)
    assert dl[1] == 0 and dl[2] == 4
    # After 4 vertices * 2 bytes = 8 bytes → next opcode at offset 11
    assert dl[11] == GX_DRAW_TRIANGLES
    assert dl[12] == 0 and dl[13] == 3
