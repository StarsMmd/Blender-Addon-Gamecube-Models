from __future__ import annotations
from dataclasses import dataclass

from .enums import ShinyChannel


@dataclass
class IRShinyFilter:
    """Shiny color filter parameters extracted from a PKX container.

    Color1 (channel_routing): Which source RGBA channel maps to each output channel.
    Only R, G, B outputs are applied in the shader; alpha passes through unchanged.

    Color2 (brightness): Per-channel brightness offset in [-1.0, 1.0].
    0 = no change, -1 = black, 1 = 2x bright. Applied as: color * (brightness + 1.0).
    Index 3 (alpha) is stored but not applied in the shader output.
    """
    channel_routing: tuple[ShinyChannel, ShinyChannel, ShinyChannel, ShinyChannel]
    brightness: tuple[float, float, float, float]
