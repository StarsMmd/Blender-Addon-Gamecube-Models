"""A lit mesh must export normals even without custom split normals.

GX hardware lighting needs per-vertex normals. The exporter's mesh describe
used to gate normal extraction on `mesh_data.has_custom_normals`, so a
from-scratch Blender mesh (which only has auto-computed normals, not custom
ones) exported with no NRM attribute. Its LIT material then had nothing to
light and rendered black/missing in-game, even though Blender — which computes
its own normals — looked fine.

`_extract_normals` now extracts from `corner_normals` regardless, and instead
respects the game's normals-XOR-vertex-colors rule: a vertex-coloured mesh
keeps colors (no normals), everything else gets normals.
"""
from types import SimpleNamespace

from exporter.phases.describe.helpers.meshes import _extract_normals


class _Identity:
    """Stands in for the coord-rotation matrix: `self @ v` returns v."""
    def __matmul__(self, v):
        return v


def _mesh(corner_normals, color_attributes=()):
    return SimpleNamespace(
        color_attributes=list(color_attributes),
        corner_normals=[SimpleNamespace(vector=n) for n in corner_normals],
    )


def test_extracts_normals_without_custom_normals():
    """THE BUG: a mesh with computed (non-custom) normals and no vertex
    colors must still produce normals — not None."""
    mesh = _mesh([(0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
    out = _extract_normals(mesh, _Identity())
    assert out == [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]


def test_skips_normals_when_vertex_colors_present():
    """Normals XOR vertex colors: a vertex-coloured mesh keeps its colors and
    omits normals so the PObject doesn't carry both."""
    mesh = _mesh([(0.0, 0.0, 1.0)], color_attributes=[SimpleNamespace(name='Col')])
    assert _extract_normals(mesh, _Identity()) is None
