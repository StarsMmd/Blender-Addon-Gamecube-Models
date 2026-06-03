"""Deprecated — superseded by the BR-based decoder.

The Blender shader-graph → IRMaterial decoder lives in two halves now:

  * `exporter/phases/describe/helpers/materials.py` serialises the
    Blender node tree into a faithful BRMaterial / BRNodeGraph.
  * `exporter/phases/plan/helpers/materials.py` walks the BRNodeGraph
    and produces an IRMaterial.

Tests that previously exercised the bpy-flavoured decoder directly
were ported to construct BR fixtures and call `plan_material` — see
`tests/test_describe_material_lighting.py` and
`tests/test_describe_texture_per_axis_wrap.py` for examples.
"""
