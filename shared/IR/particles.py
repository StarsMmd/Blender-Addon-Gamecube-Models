"""IR particle types — platform-agnostic representation of particle effects.

Stores decoded particle data from GPT1 files in generic formats.
No raw binary nodes, no Blender-specific values.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class IRParticleTexture:
    """One texture used by particle effects."""
    format: int             # GX texture format ID
    width: int = 0
    height: int = 0
    pixels: bytes = b''    # Raw RGBA pixel data (decoded from GX format)


@dataclass
class IRParticleGenerator:
    """One particle emitter definition."""
    index: int = 0
    gen_type: int = 0       # Generator type/flags
    lifetime: int = 120     # Frame duration
    max_particles: int = 0  # Max concurrent particles
    flags: int = 0          # Generator flags
    params: tuple = ()      # 12 float parameters from generator header
    instructions: list = field(default_factory=list)  # list[ParticleInstruction]


@dataclass
class IRParticleSystem:
    """Particle system from a GPT1 file.

    Attached to an IRModel when the source PKX contains GPT1 data.
    """
    generators: list = field(default_factory=list)   # list[IRParticleGenerator]
    textures: list = field(default_factory=list)      # list[IRParticleTexture]
    ref_ids: list = field(default_factory=list)        # list[int] — generator ID lookup
