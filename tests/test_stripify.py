"""Tests for the compose-side triangle stripifier.

The stripifier groups a triangle soup into GX triangle-strips plus leftover
triangles. Correctness means: re-decoding the emitted strips (with the exact
winding rules of the importer's PObject.read_geometry) reproduces the input
triangles — same faces, same winding, none dropped or duplicated — and that
attribute seams (differing vertex tokens) break strips rather than welding
across them.
"""
from collections import Counter

from exporter.phases.compose.helpers.stripify import stripify


# ---------------------------------------------------------------------------
# Decoders — mirror shared/Nodes/Classes/Mesh/PObject.py::read_geometry
# (lines 216-251) so the tests validate against the real binary semantics.
# ---------------------------------------------------------------------------

def _decode_strip(s):
    """GX_DRAW_TRIANGLE_STRIP decode: N vertices -> N-2 triangles."""
    faces = []
    for i in range(len(s) - 2):
        if i % 2 == 0:
            faces.append((s[i + 1], s[i], s[i + 2]))
        else:
            faces.append((s[i], s[i + 1], s[i + 2]))
    return faces


def _canon(face):
    """Canonical form under cyclic rotation (winding-preserving): rotate so
    the smallest token leads. Two faces share winding iff canon forms match."""
    i = face.index(min(face))
    return (face[i], face[(i + 1) % 3], face[(i + 2) % 3])


def _all_decoded_faces(triangles):
    """Run stripify, decode everything back, return the face multiset."""
    strips, leftover = stripify(triangles)
    faces = []
    for s in strips:
        faces.extend(_decode_strip(s))
    # Leftover triangles are emitted as GX_DRAW_TRIANGLES, which decode back
    # to the same IR winding they were stored in.
    faces.extend(leftover)
    return strips, leftover, faces


def _assert_roundtrip(triangles):
    """Every input triangle is reproduced exactly once, with correct winding."""
    strips, leftover, faces = _all_decoded_faces(triangles)
    assert Counter(_canon(f) for f in faces) == Counter(_canon(t) for t in triangles)
    return strips, leftover


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _grid_triangles(cols, rows):
    """A cols x rows quad grid, each quad split into two CCW triangles, all
    vertices welded (shared tokens) so strips can run. Token = vertex id."""
    def vid(x, y):
        return y * (cols + 1) + x

    tris = []
    for y in range(rows):
        for x in range(cols):
            a, b = vid(x, y), vid(x + 1, y)
            c, d = vid(x + 1, y + 1), vid(x, y + 1)
            tris.append((a, b, c))
            tris.append((a, c, d))
    return tris


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestStripifyCorrectness:

    def test_single_triangle_is_leftover(self):
        tris = [(0, 1, 2)]
        strips, leftover = _assert_roundtrip(tris)
        assert strips == []
        assert leftover == [(0, 1, 2)]

    def test_two_adjacent_triangles_form_one_strip(self):
        # Quad (0,1,2,3) split into (0,1,2) and (0,2,3), sharing edge 0-2.
        tris = [(0, 1, 2), (0, 2, 3)]
        strips, leftover = _assert_roundtrip(tris)
        assert len(strips) == 1
        assert leftover == []
        assert len(strips[0]) == 4  # 2 triangles -> 4 strip vertices

    def test_grid_roundtrips_and_compresses(self):
        tris = _grid_triangles(4, 4)        # 32 triangles
        strips, leftover = _assert_roundtrip(tris)
        # Compression: far fewer GX primitives than 32 triangle draws.
        n_prims = len(strips) + (1 if leftover else 0)
        assert n_prims < len(tris)
        # Most triangles should land in strips, not leftover.
        assert len(leftover) < len(tris) // 2

    def test_winding_is_a_bijection(self):
        tris = _grid_triangles(3, 5)
        _, _, faces = _all_decoded_faces(tris)
        # Exact one-to-one match of faces (no dropped/duplicated/flipped).
        assert len(faces) == len(tris)
        assert Counter(_canon(f) for f in faces) == Counter(_canon(t) for t in tris)

    def test_seam_breaks_the_strip(self):
        # Two triangles adjacent in geometry but the shared edge uses DIFFERENT
        # tokens on each side (an attribute seam): tokens 2/3 vs 20/30. They
        # must not be welded into a strip.
        tris = [(0, 1, 2), (10, 30, 20)]
        strips, leftover = _assert_roundtrip(tris)
        assert strips == []
        assert Counter(leftover) == Counter(tris)

    def test_partial_seam_still_roundtrips(self):
        # A run of welded triangles, then a seam, then another welded run.
        welded = _grid_triangles(3, 1)                 # shares tokens 0..7
        seam = [(100, 101, 102), (100, 102, 103)]      # disjoint token set
        tris = welded + seam
        strips, leftover = _assert_roundtrip(tris)
        # Both regions strip independently; no strip mixes the two token sets.
        for s in strips:
            toks = set(s)
            assert toks.isdisjoint({100, 101, 102, 103}) or toks <= {100, 101, 102, 103}

    def test_degenerate_triangle_is_leftover_not_crash(self):
        tris = [(0, 1, 1), (2, 3, 4)]      # first is degenerate
        strips, leftover = stripify(tris)
        assert (0, 1, 1) in leftover
        # Non-degenerate single triangle also can't form a strip alone.
        assert (2, 3, 4) in leftover
        assert strips == []

    def test_fan_vertex_shared_by_many_triangles(self):
        # Triangle fan around center vertex 0 — high-degree hub, must not crash
        # and must round-trip.
        tris = [(0, i, i + 1) for i in range(1, 8)]
        _assert_roundtrip(tris)

    def test_empty_input(self):
        assert stripify([]) == ([], [])

    def test_determinism(self):
        tris = _grid_triangles(4, 4)
        assert stripify(tris) == stripify(tris)

    def test_min_strip_tris_threshold(self):
        # With a high threshold even a stripable pair falls back to triangles.
        tris = [(0, 1, 2), (0, 2, 3)]
        strips, leftover = stripify(tris, min_strip_tris=3)
        assert strips == []
        assert Counter(leftover) == Counter(tris)
