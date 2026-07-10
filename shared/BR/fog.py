from __future__ import annotations
from dataclasses import dataclass


@dataclass
class BRFog:
    """Scene fog as Blender-native World Mist settings.

    The GX fog (type / start_z / end_z / RGBA color) is mapped in Plan onto
    Blender's ``world.mist_settings`` (start / depth / falloff) plus the
    world background colour. This is a *lossy* mapping — GX has more fog
    types than Blender has falloff modes, the color alpha is dropped, and
    degenerate map-fog values don't survive — which is accepted (see the
    round-trip doc's leniency note). BR must not import IR, so this mirrors
    no IR type directly.
    """
    color: tuple[float, float, float] = (0.0, 0.0, 0.0)  # linear 0-1, world bg
    mist_start: float = 0.0
    mist_depth: float = 0.0
    falloff: str = 'LINEAR'  # Blender enum: QUADRATIC / LINEAR / INVERSE_QUADRATIC
    intensity: float = 0.0
