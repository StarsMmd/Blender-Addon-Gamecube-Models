from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class BRLightAnimation:
    """Pre-converted light animation keyframes.

    Mirrors BRCameraAnimation: position channels are already in Blender Z-up
    space (the eye/interest coord flip happens in Plan); colour, visibility,
    and cutoff channels are straight pass-through. Channel lists hold
    IRKeyframe objects (typed ``list`` to avoid an IR import). Map light
    animations in the corpus are empty presence clips, so every channel is
    usually an empty list — the clip's very existence is the data.
    """
    name: str
    color_r: list = field(default_factory=list)   # list[IRKeyframe]
    color_g: list = field(default_factory=list)
    color_b: list = field(default_factory=list)
    color_a: list = field(default_factory=list)
    visibility: list = field(default_factory=list)
    cutoff: list = field(default_factory=list)
    loc_x: list = field(default_factory=list)
    loc_y: list = field(default_factory=list)
    loc_z: list = field(default_factory=list)
    target_loc_x: list = field(default_factory=list)
    target_loc_y: list = field(default_factory=list)
    target_loc_z: list = field(default_factory=list)
    end_frame: float = 0.0
    loop: bool = False


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
    animations: list[BRLightAnimation] = field(default_factory=list)
