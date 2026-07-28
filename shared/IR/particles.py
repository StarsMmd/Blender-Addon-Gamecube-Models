"""IR particle types — platform-agnostic representation of particle effects.

The particle IR describes a particle system in the shared vocabulary of
general-purpose engines (emission, birth state with randomness ranges,
over-life curves/gradients, forces, texture-sheet animation, sub-emitters,
render mode) — it carries no source-format opcodes, headers, or register
state. Producers (game-format describe) summarize their native encoding
into these semantics; consumers (Blender build, game-format compose)
synthesize their native encoding from them. Both directions are allowed
to be lossy approximations.

Some fields are core particle-system features that a given target may not
fully represent (e.g. trail rendering, velocity-stretched billboards);
targets approximate or ignore what they can't express.

Conventions (matching the rest of the IR — see ir_specification.md):
- positions/velocities: meters, Y-up right-handed (velocity per frame)
- rotation: radians (billboard roll around the view axis)
- colors: sRGB floats [0, 1]
- durations (lifetimes, event frames): frames
- over-life keys/stops: age normalized to [0, 1] over the particle's life
- randomness: uniform in [base - spread, base + spread]
"""
from __future__ import annotations
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Generic value primitives
# ---------------------------------------------------------------------------


@dataclass
class IRRandomScalar:
    """A scalar drawn uniformly from [base - spread, base + spread]."""
    base: float = 0.0
    spread: float = 0.0


@dataclass
class IRRandomVec3:
    """A vector whose components are drawn uniformly from base ± spread."""
    base: tuple = (0.0, 0.0, 0.0)
    spread: tuple = (0.0, 0.0, 0.0)


@dataclass
class IRColorStop:
    """One stop of a color-over-life gradient."""
    age: float = 0.0        # normalized [0, 1]
    rgba: tuple = (1.0, 1.0, 1.0, 1.0)   # sRGB [0, 1]


@dataclass
class IRScalarKey:
    """One key of a scalar-over-life curve (linear interpolation between keys)."""
    age: float = 0.0        # normalized [0, 1]
    value: float = 0.0


# ---------------------------------------------------------------------------
# Emitter building blocks
# ---------------------------------------------------------------------------


@dataclass
class IRParticleEmission:
    """How many particles appear, and when."""
    rate: float = 0.0       # particles per frame, continuous emission
    bursts: tuple = ()      # ((frame, count), ...) — instantaneous bursts


@dataclass
class IRParticleBirth:
    """Initial particle state at spawn."""
    position: IRRandomVec3 = field(default_factory=IRRandomVec3)  # offset from emitter, meters
    velocity: IRRandomVec3 = field(default_factory=IRRandomVec3)  # meters per frame
    size: IRRandomScalar = field(default_factory=lambda: IRRandomScalar(base=1.0))
    color_spread: tuple = (0.0, 0.0, 0.0, 0.0)   # per-channel ± randomization of the birth color


@dataclass
class IRParticleRotation:
    """Billboard roll animation."""
    initial: IRRandomScalar = field(default_factory=IRRandomScalar)  # radians at birth
    rate: IRRandomScalar = field(default_factory=IRRandomScalar)     # radians per frame
    accel: float = 0.0                                               # radians per frame^2


@dataclass
class IRParticleForces:
    """Continuous forces applied every frame of a particle's life."""
    gravity: tuple = (0.0, 0.0, 0.0)   # constant acceleration, meters/frame^2, Y-up
    drag: float = 0.0                  # fraction of velocity lost per frame [0, 1]


@dataclass
class IRParticleTextureAnim:
    """Texture-sheet (flip-book) animation over particle age."""
    frames: tuple = ()        # indices into IRParticleSystem.textures
    frame_ages: tuple = ()    # normalized [0, 1] age each frame becomes visible
    filter: str = "LINEAR"    # NEAREST | LINEAR
    wrap_s: str = "CLAMP"     # CLAMP | MIRROR
    wrap_t: str = "CLAMP"


@dataclass
class IRParticleRender:
    """How each particle is drawn."""
    blend_mode: str = "ALPHA"       # ALPHA | ADD | MULTIPLY
    billboard: str = "CAMERA"       # CAMERA | VELOCITY_STRETCH | NONE
    textured: bool = True           # False = untextured solid-color quads
    depth_test: bool = True
    trail_length: float = 0.0       # ribbon/motion-trail length, meters (0 = off)


@dataclass
class IRSubEmitter:
    """A child emitter triggered at a point in the parent particle's life."""
    age: float = 0.0                # normalized [0, 1] trigger point (0 = birth, 1 = death)
    emitter_ref: int = -1           # index into IRParticleSystem.emitters
    count: int = 1
    inherit_velocity: bool = False


# ---------------------------------------------------------------------------
# Emitter / system / binding
# ---------------------------------------------------------------------------


@dataclass
class IRParticleEmitter:
    """One particle emitter: emission behaviour plus per-particle life curves."""
    name: str = ""
    emit_duration: float = 120.0    # frames the emitter keeps spawning
    max_particles: int = 0          # concurrent-particle budget
    particle_lifetime: IRRandomScalar = field(default_factory=IRRandomScalar)  # frames
    looping: bool = False           # per-particle animation cycles until death
    emission: IRParticleEmission = field(default_factory=IRParticleEmission)
    birth: IRParticleBirth = field(default_factory=IRParticleBirth)
    color_over_life: list = field(default_factory=list)   # list[IRColorStop]
    size_over_life: list = field(default_factory=list)    # list[IRScalarKey], absolute particle size (quad scale)
    rotation: IRParticleRotation = field(default_factory=IRParticleRotation)
    forces: IRParticleForces = field(default_factory=IRParticleForces)
    texture: IRParticleTextureAnim = field(default_factory=IRParticleTextureAnim)
    render: IRParticleRender = field(default_factory=IRParticleRender)
    sub_emitters: list = field(default_factory=list)      # list[IRSubEmitter]


@dataclass
class IRParticleTexture:
    """One texture used by particle emitters."""
    width: int = 0
    height: int = 0
    pixels: bytes = b''     # raw u8 RGBA, row-major, bottom-to-top (IR image convention)


@dataclass
class IRParticleEmitEvent:
    """One animation-driven spawn: an emitter fired from a bone at a frame.

    Lives on a bone's animation track (IRBoneTrack.particle_emits) — the
    bone that owns the track is the attach point, and the spawned emitter
    follows that bone.
    """
    frame: float = 0.0      # clip-local frame
    emitter_ref: int = -1   # index into IRParticleSystem.emitters


@dataclass
class IRParticleSystem:
    """All particle emitters and textures belonging to one model."""
    emitters: list = field(default_factory=list)    # list[IRParticleEmitter]
    textures: list = field(default_factory=list)    # list[IRParticleTexture]
