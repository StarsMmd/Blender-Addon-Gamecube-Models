"""Triangle-soup → GX triangle-strip grouping for display-list encoding.

The IR stores geometry as triangle (and quad) faces only — the original GX
strip/fan grouping is decoded away at import. To emit compact GX display
lists on export we regenerate strips algorithmically here, from the triangle
soup alone, with no import-side metadata.

Each input triangle is an ordered triple of opaque *vertex tokens*, in the
winding the importer decodes a triangle to (the IR face winding). Tokens
compare by value: two corners with identical tokens are the same vertex and
may be welded into a strip; corners differing in any attribute (position,
normal, UV, colour, matrix index) carry different tokens and so break the
strip — which is exactly where attribute seams must split.

A grown strip ``[w0, w1, w2, ...]`` is decoded by the importer
(``PObject.read_geometry``) as, for triangle ``i`` in ``0..len-3``::

    even i:  (w[i+1], w[i],   w[i+2])
    odd  i:  (w[i],   w[i+1], w[i+2])

Strips are grown so each decoded triangle is winding-equal (a cyclic
rotation) to its source triangle. Every extension is validated against this
decode before being accepted, so the grouping can never flip a triangle's
winding: a candidate that would is rejected and the strip ends instead.
Worst case the strips are short (more, smaller chunks) — never wrong
geometry.
"""
from collections import defaultdict


def _winding_equal(a, b):
    """True when triangles ``a`` and ``b`` are the same face — equal up to a
    cyclic rotation (which preserves winding), but not a reversal."""
    return b == a or b == (a[1], a[2], a[0]) or b == (a[2], a[0], a[1])


def _third(tri, p, q):
    """The single token of ``tri`` that is neither ``p`` nor ``q``.

    Returns None when ``tri`` does not contain exactly one such token (e.g. it
    does not actually hold both ``p`` and ``q``, or has repeated tokens)."""
    rem = [t for t in tri if t != p and t != q]
    return rem[0] if len(rem) == 1 else None


def stripify(triangles, min_strip_tris=2):
    """Group triangles into GX triangle-strips plus leftover triangles.

    Args:
        triangles: list[tuple[token, token, token]] — each triangle's three
            vertex tokens in IR face winding. Tokens must be hashable and
            compare by value.
        min_strip_tris: minimum triangles a strip must cover to be emitted as
            a strip; shorter runs fall back to the leftover triangle list (a
            1-triangle "strip" costs the same as a triangle, so there is no
            point emitting it as one).

    Returns:
        (strips, leftover):
            strips: list[list[token]] — each a strip's vertex token sequence
                (length >= min_strip_tris + 2).
            leftover: list[tuple[token, token, token]] — triangles not placed
                in any strip, in IR face winding (emit as GX_DRAW_TRIANGLES).
    """
    n = len(triangles)
    used = [False] * n
    # A triangle with a repeated token is degenerate; never strip it.
    degenerate = [len(set(t)) < 3 for t in triangles]

    # edge (frozenset of two tokens) -> triangle indices touching that edge.
    edge_tris = defaultdict(list)
    for i, t in enumerate(triangles):
        if degenerate[i]:
            continue
        a, b, c = t
        edge_tris[frozenset((a, b))].append(i)
        edge_tris[frozenset((b, c))].append(i)
        edge_tris[frozenset((c, a))].append(i)

    def _live_on(edge, exclude):
        for j in edge_tris.get(edge, ()):
            if j != exclude and not used[j] and not degenerate[j]:
                yield j

    def _initial_degree(i):
        a, b, c = triangles[i]
        d = 0
        for u, v in ((a, b), (b, c), (c, a)):
            d += sum(1 for j in edge_tris[frozenset((u, v))] if j != i
                     and not degenerate[j])
        return d

    # Seed from the lowest-connectivity triangles first — they have the fewest
    # ways to be reached later, so consuming them early grows longer strips.
    # Ties keep input order (stable sort) for deterministic output.
    order = sorted((i for i in range(n) if not degenerate[i]),
                   key=_initial_degree)

    strips = []
    leftover = []

    for seed in order:
        if used[seed]:
            continue
        a, b, c = triangles[seed]
        strip = [b, a, c]          # decodes (even i=0) back to (a, b, c)
        strip_tris = [seed]
        used[seed] = True

        # Grow forward off the trailing edge (strip[-2], strip[-1]).
        while True:
            p, q = strip[-2], strip[-1]
            chosen = None
            for j in _live_on(frozenset((p, q)), exclude=strip_tris[-1]):
                x = _third(triangles[j], p, q)
                if x is None:
                    continue
                # The face the importer would decode for this new strip vertex.
                if (len(strip) - 2) % 2 == 0:
                    cand = (strip[-1], strip[-2], x)
                else:
                    cand = (strip[-2], strip[-1], x)
                if _winding_equal(triangles[j], cand):
                    chosen = (j, x)
                    break
            if chosen is None:
                break
            j, x = chosen
            strip.append(x)
            strip_tris.append(j)
            used[j] = True

        if len(strip_tris) >= min_strip_tris:
            strips.append(strip)
        else:
            # Below threshold: emit every triangle the run consumed (not just
            # the seed) as a plain triangle, or they would be silently dropped.
            for ti in strip_tris:
                leftover.append(triangles[ti])

    # Degenerate triangles were never seeded; emit them as plain triangles.
    for i in range(n):
        if degenerate[i] and not used[i]:
            leftover.append(triangles[i])

    return strips, leftover
