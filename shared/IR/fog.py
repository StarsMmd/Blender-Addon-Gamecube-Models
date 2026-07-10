from __future__ import annotations
from dataclasses import dataclass


@dataclass
class IRFog:
    """Scene fog (HSD_Fog).

    `start_z` / `end_z` are eye-space distances in the game's native GC
    units and are carried verbatim (not converted to meters) so the raw
    float bits round-trip exactly — some map archives store a degenerate
    fog whose fields are leftover pointer values, and any float scaling
    would corrupt them. `color` is the RGBA u8 tuple as stored in the
    inline HSD_Color.
    """
    type: int = 0
    start_z: float = 0.0
    end_z: float = 0.0
    color: tuple[int, int, int, int] = (0, 0, 0, 0)
    has_adj: bool = False
    name: str = "Fog"
