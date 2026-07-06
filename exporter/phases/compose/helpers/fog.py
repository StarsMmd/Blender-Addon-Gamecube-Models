"""Compose an IRFog into a Fog node."""
try:
    from .....shared.Nodes.Classes.Fog.Fog import Fog
    from .....shared.Nodes.Classes.Fog.FogAdj import FogAdj
    from .....shared.Nodes.Classes.Colors.RGBAColor import RGBAColor
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.Nodes.Classes.Fog.Fog import Fog
    from shared.Nodes.Classes.Fog.FogAdj import FogAdj
    from shared.Nodes.Classes.Colors.RGBAColor import RGBAColor
    from shared.helpers.logger import StubLogger


def compose_fog(ir_fog, logger=StubLogger()):
    """Convert an IRFog into a Fog node.

    Args:
        ir_fog: IRFog from the IR, or None.
        logger: Logger instance.

    Returns:
        Fog node, or None if ir_fog is None.

    IRFog Z distances are already in GC units (carried verbatim, not scaled
    — see shared/IR/fog.py), so nothing here touches them.
    """
    if ir_fog is None:
        return None

    fog = Fog(address=None, blender_obj=None)
    fog.type = ir_fog.type
    fog.adj = FogAdj(address=None, blender_obj=None) if ir_fog.has_adj else None
    fog.start_z = ir_fog.start_z
    fog.end_z = ir_fog.end_z

    r, g, b, a = ir_fog.color
    color = RGBAColor(address=None, blender_obj=None)
    color.red, color.green, color.blue, color.alpha = r, g, b, a
    fog.color = color

    logger.info("    Composed fog (type=0x%X)", ir_fog.type)
    return fog
