"""Shiny filter parameters dataclass.

Stores the channel routing and brightness values extracted from PKX headers.
Used by both the importer (extract phase) and exporter (describe/package phases).
"""
from dataclasses import dataclass


@dataclass
class ShinyParams:
    """Shiny color filter parameters from a PKX model header.

    route_r/g/b/a: int (0-3) — which source RGBA channel maps to each output channel.
        0=Red, 1=Green, 2=Blue, 3=Alpha.
    brightness_r/g/b/a: float (-1.0 to 1.0) — per-channel brightness adjustment.
    """
    route_r: int
    route_g: int
    route_b: int
    route_a: int
    brightness_r: float
    brightness_g: float
    brightness_b: float
    brightness_a: float
