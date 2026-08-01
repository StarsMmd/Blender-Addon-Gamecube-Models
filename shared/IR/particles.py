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
- sizes: meters — a particle's quad width, on the same scale as the model,
  so a consumer places and sizes particles in one coordinate system
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
class IREmissionShape:
    """Where newborn particles appear and which way they fly.

    Defined in the emitter's local frame with +Z the emission axis; the
    consumer orients that frame however the emitter itself is oriented
    (for bone-fired emitters, the firing bone).

    kinds and which fields they read:
    - ``DISC``: particles on a disc in the XY plane. ``radius`` (``ring``
      = rim only, ``uniform_area`` = uniform-by-area sampling), azimuth in
      [``arc_start``, ``arc_end``] (both zero = the full circle),
      ``cone_angle`` tilts the velocity away from +Z proportionally to
      each particle's radius fraction (rim particles get the full angle —
      a cone profile). ``sweep`` spaces one frame's spawns evenly along
      the arc instead of randomly.
    - ``BOX``: particles fill the box spanned by ``box_extents`` (signed,
      from the local origin). A negative extent emits on that axis's far
      face instead of filling the axis — a sheet/shell.
    - ``SPHERE``: particles on directions up to ``polar_max`` from +Z at
      the sampled radius, flying radially at ``radial_speed`` (negative =
      inward; when both ``ring`` and inward, speed scales with the radius
      fraction).

    ``velocity`` is the authored emitter-frame velocity vector (DISC/BOX
    fly at its magnitude — DISC along the cone, BOX along ±Z).
    """
    kind: str = 'DISC'                 # DISC | BOX | SPHERE
    radius: float = 0.0                # meters (DISC, SPHERE)
    ring: bool = False                 # rim/shell emission instead of volume fill
    uniform_area: bool = False         # sqrt sampling + speed scaled by radius fraction
    cone_angle: float = 0.0            # radians (DISC)
    arc_start: float = 0.0             # radians (DISC)
    arc_end: float = 0.0
    sweep: bool = False                # evenly space one frame's spawns along the arc
    box_extents: tuple = (0.0, 0.0, 0.0)   # meters, signed (BOX)
    polar_max: float = 0.0             # radians (SPHERE); 0 = full sphere
    radial_speed: float = 0.0          # meters/frame (SPHERE), signed
    velocity: tuple = (0.0, 0.0, 0.0)  # meters/frame, emitter frame (DISC/BOX speed)
    type_flags: int = 0                # renderer-variant bits of unknown meaning,
                                       # carried so the source type reconstructs
    behaviour_flags: int = 0           # runtime behaviour bits, partially decoded:
                                       # the blend field is lifted out into
                                       # IRParticleRender.blend_mode; the rest
                                       # (motion/orientation variants) are carried
                                       # until their semantics are recovered


@dataclass
class IRParticleEmission:
    """How many particles appear, and when."""
    rate: float = 0.0       # mean particles per frame, continuous emission
    rate_jitter: bool = False   # each frame draws rate x uniform[0, 2] instead of exactly rate
    bursts: tuple = ()      # ((frame, count), ...) — instantaneous bursts
    shape: IREmissionShape = field(default_factory=IREmissionShape)


@dataclass
class IRParticleBirth:
    """Initial particle state at spawn."""
    position: IRRandomVec3 = field(default_factory=IRRandomVec3)  # offset from emitter, meters
    velocity: IRRandomVec3 = field(default_factory=IRRandomVec3)  # meters per frame
    size: IRRandomScalar = field(default_factory=lambda: IRRandomScalar(base=1.0))  # meters
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
    blend_mode: str = "ALPHA"       # ALPHA | ADD | SUBTRACT | MULTIPLY
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
