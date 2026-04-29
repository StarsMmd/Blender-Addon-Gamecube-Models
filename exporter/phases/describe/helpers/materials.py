"""Snapshot Blender materials into BRMaterial dataclasses.

Interim: the heavy shader-graph → GX-combiner decoding still lives in the
legacy `describe_blender/helpers/materials.py::describe_material`. This
helper wraps that output in a BRMaterial shell so the rest of the
pipeline runs through the BR layer. A future pass can faithfully
serialise `bpy_material.node_tree` into BRNodeGraph and move the decode
logic into plan_material.
"""
try:
    from .....shared.BR.materials import BRMaterial, BRNodeGraph
    from .....shared.helpers.logger import StubLogger
    from .materials_decode import describe_material as _legacy_describe_material
except (ImportError, SystemError):
    from shared.BR.materials import BRMaterial, BRNodeGraph
    from shared.helpers.logger import StubLogger
    from exporter.phases.describe.helpers.materials_decode import (
        describe_material as _legacy_describe_material,
    )


def describe_material(blender_mat, logger=StubLogger(),
                      cache=None, image_cache=None):
    """Read one Blender material into a BRMaterial.

    In: blender_mat (bpy.types.Material); logger; cache / image_cache
        (dicts shared across a model so identical Blender materials and
        images share BRMaterial / IR image objects).
    Out: BRMaterial. The decoded IRMaterial lives on
         ``br_material._ir_material`` until the shader-graph decoder
         migrates into plan.
    """
    cache_key = id(blender_mat)
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    ir_material = _legacy_describe_material(
        blender_mat, logger=logger,
        cache=None, image_cache=image_cache,
    )

    br = BRMaterial(
        name=blender_mat.name,
        node_graph=BRNodeGraph(),
        use_backface_culling=blender_mat.use_backface_culling,
        blend_method=getattr(blender_mat, 'blend_method', None),
        dedup_key=(id(ir_material),),
    )
    br._ir_material = ir_material  # interim until decode moves into plan

    if cache is not None:
        cache[cache_key] = br
    return br
