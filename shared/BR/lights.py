from __future__ import annotations
from dataclasses import dataclass


@dataclass
class BRLight:
    """One Blender light — blender_type is the exact bpy enum string.

    Ambient lights have no Blender equivalent, so Plan emits them as
    zero-energy POINT lights with ``is_ambient=True`` so build can stamp
    the ``dat_light_type`` custom property for round-trip export.
    """
    name: str
    blender_type: str  # 'POINT' / 'SUN' / 'SPOT'
    color: tuple[float, float, float]  # linear RGB (sRGB already converted)
    energy: float
    location: tuple[float, float, float] | None = None  # Blender-space (Z-up)
    target_location: tuple[float, float, float] | None = None
    is_ambient: bool = False
