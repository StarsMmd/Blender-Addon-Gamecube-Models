"""Describe a Fog node into an IRFog dataclass."""
try:
    from .....shared.IR.fog import IRFog
except (ImportError, SystemError):
    from shared.IR.fog import IRFog


def describe_fog(fog_node):
    """Convert a parsed Fog node to an IRFog.

    In: fog_node (Fog, parsed) or None.
    Out: IRFog carrying type/start_z/end_z/color/adj-presence verbatim, or
         None if fog_node is None.

    Fog Z distances are kept in the game's native GC units (see IRFog) — no
    meters conversion, so the raw values round-trip exactly.
    """
    if fog_node is None:
        return None

    color = (0, 0, 0, 0)
    c = getattr(fog_node, 'color', None)
    if c is not None:
        color = (c.red, c.green, c.blue, c.alpha)

    return IRFog(
        type=getattr(fog_node, 'type', 0),
        start_z=getattr(fog_node, 'start_z', 0.0),
        end_z=getattr(fog_node, 'end_z', 0.0),
        color=color,
        has_adj=getattr(fog_node, 'adj', None) is not None,
    )
