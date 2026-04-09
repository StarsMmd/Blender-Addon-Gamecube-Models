"""GPT1 generator simulator — emits particles over time and tracks their states.

Uses gpt1_interpreter to simulate individual particles. Provides the per-frame
state data needed by the Blender build phase to create keyframed billboards.
"""
import math
import random as _random
from .gpt1_interpreter import interpret_particle, ParticleState


def simulate_generator(generator_def, num_frames=None, max_tracked=8, seed=42):
    """Simulate a generator emitting particles over its lifetime.

    Args:
        generator_def: GeneratorDef from the GPT1 parser.
        num_frames: Number of frames to simulate. Defaults to generator lifetime.
        max_tracked: Maximum number of particles to track (for performance).
        seed: Random seed for reproducible results.

    Returns:
        list of list[ParticleState] — one timeline per tracked particle.
        Each timeline is the output of interpret_particle().
    """
    _random.seed(seed)

    if num_frames is None:
        num_frames = max(generator_def.lifetime, 30)

    lifetime = max(generator_def.lifetime, 1)
    max_particles = max(generator_def.max_particles, 1)

    # Emission rate: spread particles evenly over the generator lifetime
    # But cap tracked particles for performance
    emit_count = min(max_particles, max_tracked)
    emit_interval = max(lifetime // emit_count, 1)

    params = generator_def.params if len(generator_def.params) >= 12 else (0.0,) * 12
    command_bytes = generator_def.command_bytes

    timelines = []

    for i in range(emit_count):
        spawn_frame = i * emit_interval

        # Create initial state with emission position and velocity
        initial = ParticleState()
        initial.gravity = params[0] if abs(params[0]) > 1e-6 else 0.0
        initial.position, initial.velocity = _compute_emission(params, initial.gravity)

        # Simulate this particle from its spawn frame
        remaining_frames = num_frames - spawn_frame
        if remaining_frames <= 0:
            continue

        snapshots = interpret_particle(command_bytes, initial, max_frames=remaining_frames)

        # Offset frame numbers to account for spawn time
        for snap in snapshots:
            snap.frame += spawn_frame

        timelines.append(snapshots)

    return timelines


def _compute_emission(params, gravity):
    """Compute initial position and velocity for a spawned particle.

    Simplified approximation of the game's generateParticle function.
    Uses generator params to determine whether this is a velocity-based
    effect (fire, smoke) or a position-based effect (sparkles, auras).

    Param layout differs by effect type:
      Fire-type (gravity != 0):
        p0=gravity, p7/p8=spread, p9=vert_spread, p11=speed
      Sparkle-type (gravity == 0):
        p9/p10/p11=spawn volume radius XYZ

    Returns (position, velocity) as two 3-element lists.
    """
    has_gravity = abs(gravity) > 1e-6

    if has_gravity:
        # Velocity-based: particles emit with speed and drift with gravity
        speed = params[11] if abs(params[11]) > 1e-6 else 0.5
        spread_x = params[7] if abs(params[7]) > 1e-6 else 1.0
        spread_y = params[9] if abs(params[9]) > 1e-6 else 1.0
        spread_z = params[8] if abs(params[8]) > 1e-6 else 1.0

        angle = _random.random() * 2 * math.pi
        spread = _random.random() * 0.3

        vx = math.sin(angle) * spread * spread_x * speed
        vy = speed * spread_y * (0.5 + 0.5 * _random.random())
        vz = math.cos(angle) * spread * spread_z * speed

        return [0.0, 0.0, 0.0], [vx, vy, vz]
    else:
        # Position-based: particles spawn at random positions, minimal velocity
        radius_x = params[9] if abs(params[9]) > 1e-6 else 1.0
        radius_y = params[10] if abs(params[10]) > 1e-6 else 1.0
        radius_z = params[11] if abs(params[11]) > 1e-6 else 1.0

        px = (2 * _random.random() - 1) * radius_x
        py = (2 * _random.random() - 1) * radius_y
        pz = (2 * _random.random() - 1) * radius_z

        # Tiny random drift
        vx = (2 * _random.random() - 1) * 0.01
        vy = (2 * _random.random() - 1) * 0.01
        vz = (2 * _random.random() - 1) * 0.01

        return [px, py, pz], [vx, vy, vz]
