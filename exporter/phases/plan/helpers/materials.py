"""Plan BRMaterial list into IRMaterial list.

Pure — no bpy. During the migration BRMaterial carries an IRMaterial
side-channel built by the legacy decoder (see
`exporter/phases/describe/helpers/materials.py`); this helper just
unwraps it. When the decoder migrates fully, plan_material will read
BRNodeGraph nodes and produce IRMaterial directly.
"""
try:
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def plan_material(br_material, logger=StubLogger()):
    """Convert one BRMaterial to an IRMaterial.

    In: br_material (BRMaterial).
    Out: IRMaterial.
    """
    ir = getattr(br_material, '_ir_material', None)
    if ir is None:
        raise ValueError(
            "plan_material: BRMaterial '%s' has no _ir_material; the "
            "shader-graph decoder hasn't been migrated into plan yet."
            % br_material.name
        )
    return ir


def plan_materials(br_materials, logger=StubLogger()):
    """Convert a list of BRMaterials to IRMaterials, preserving order."""
    return [plan_material(m, logger=logger) for m in br_materials]
