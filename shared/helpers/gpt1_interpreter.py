"""GPT1 particle bytecode interpreter.

Simulates per-particle state by executing the command bytecode frame-by-frame,
matching the behavior of psInterpretParticle0 in the game.

Key behavioral notes from the XD disassembly:
  - Particles start with prim_color = (255, 255, 255, 255) (white, fully opaque)
  - LIFETIME commands (< 0x80) BREAK out of the command loop and set a wait counter
  - Commands >= 0x80 execute inline and the loop continues to the next command
  - Physics (gravity, friction, velocity→position) applies EVERY frame, including during waits
  - Scale/color/rotation interpolation also runs every frame during waits
  - A particle is visible from the moment it spawns (with default white color)
"""
import math
import struct
import random as _random
from dataclasses import dataclass, field


@dataclass
class ParticleState:
    """Per-frame state of a single particle."""
    alive: bool = True
    frame: int = 0

    # Spatial
    position: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    velocity: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    gravity: float = 0.0
    friction: float = 1.0

    # Visual
    size: float = 1.0
    size_target: float = 1.0
    size_time: int = 0       # frames remaining for size interpolation

    rotation: float = 0.0
    rot_rate: float = 0.0
    rot_accel: float = 0.0
    rot_time: int = 0

    prim_color: list = field(default_factory=lambda: [255, 255, 255, 255])
    prim_target: list = field(default_factory=lambda: [255, 255, 255, 255])
    prim_time: int = 0

    env_color: list = field(default_factory=lambda: [0, 0, 0, 0])
    env_target: list = field(default_factory=lambda: [0, 0, 0, 0])
    env_time: int = 0

    texture_index: int = -1

    # Interpreter state
    cmd_pos: int = 0        # byte offset in command stream
    wait_frames: int = 0    # var1A countdown
    loop_count: int = 0     # loop iteration counter
    loop_pos: int = 0       # saved loop start position
    jump_pos: int = 0       # saved jump position

    def snapshot(self):
        """Create a deep copy suitable for recording in a timeline."""
        s = ParticleState(
            alive=self.alive, frame=self.frame,
            position=list(self.position), velocity=list(self.velocity),
            gravity=self.gravity, friction=self.friction,
            size=self.size, size_target=self.size_target, size_time=self.size_time,
            rotation=self.rotation, rot_rate=self.rot_rate,
            rot_accel=self.rot_accel, rot_time=self.rot_time,
            prim_color=list(self.prim_color), prim_target=list(self.prim_target),
            prim_time=self.prim_time,
            env_color=list(self.env_color), env_target=list(self.env_target),
            env_time=self.env_time,
            texture_index=self.texture_index,
            cmd_pos=self.cmd_pos, wait_frames=self.wait_frames,
            loop_count=self.loop_count, loop_pos=self.loop_pos,
            jump_pos=self.jump_pos,
        )
        return s


def interpret_particle(command_bytes, initial_state=None, max_frames=300):
    """Simulate one particle by executing its command bytecode frame by frame.

    Args:
        command_bytes: Raw bytecode from a GeneratorDef.
        initial_state: Optional ParticleState with pre-set position/velocity.
                       If None, starts with defaults (origin, white, opaque).
        max_frames: Maximum frames to simulate (safety cap).

    Returns:
        list[ParticleState] — one snapshot per frame (deep copies).
    """
    state = initial_state if initial_state is not None else ParticleState()
    data = command_bytes
    snapshots = []

    for frame in range(max_frames):
        state.frame = frame

        # 1. Decrement wait counter
        if state.wait_frames > 0:
            state.wait_frames -= 1

        # 2. If wait reached 0, execute commands until next LIFETIME or EXIT
        if state.wait_frames == 0 and state.alive:
            _execute_commands(state, data)

        if not state.alive:
            snapshots.append(state.snapshot())
            break

        # 3. Apply physics (every frame, including during waits)
        _apply_physics(state)

        # 4. Interpolate animated properties
        _interpolate_size(state)
        _interpolate_color(state)
        _interpolate_rotation(state)

        # 5. Record snapshot
        snapshots.append(state.snapshot())

    return snapshots


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------

def _execute_commands(state, data):
    """Execute commands from current cmd_pos until a non-zero LIFETIME or EXIT."""
    while state.cmd_pos < len(data):
        opcode = data[state.cmd_pos]
        state.cmd_pos += 1

        if opcode < 0x80:
            # LIFETIME command — may break the loop
            wait = _exec_lifetime(state, data, opcode)
            if wait > 0:
                state.wait_frames = wait
                return  # break out of command loop
            # wait=0: continue to next command
        elif opcode in (0xFE, 0xFF):
            state.alive = False
            return
        else:
            _exec_complex(state, data, opcode)

    # Ran off the end of commands → kill
    state.alive = False


def _exec_lifetime(state, data, opcode):
    """Process a LIFETIME (< 0x80) opcode. Returns wait frame count."""
    low5 = opcode & 0x1F
    frames = low5

    # Bit 5: extended — read second byte
    if opcode & 0x20:
        if state.cmd_pos < len(data):
            ext = data[state.cmd_pos]
            state.cmd_pos += 1
            frames = (low5 << 8) | ext

    # Bit 6: load texture
    if opcode & 0x40:
        if state.cmd_pos < len(data):
            state.texture_index = data[state.cmd_pos]
            state.cmd_pos += 1

    return frames


def _exec_complex(state, data, opcode):
    """Execute a complex opcode (>= 0x80)."""
    # Dispatch based on opcode ranges
    if 0x80 <= opcode <= 0x87:
        _exec_set_pos(state, data, opcode)
    elif 0x88 <= opcode <= 0x8F:
        _exec_move(state, data, opcode)
    elif 0x90 <= opcode <= 0x97:
        _exec_set_vel(state, data, opcode)
    elif 0x98 <= opcode <= 0x9F:
        _exec_accel(state, data, opcode)
    elif opcode == 0xA0:
        _exec_scale(state, data)
    elif opcode == 0xA1:
        pass  # TEX_OFF — texture display flag, cosmetic
    elif opcode == 0xA2:
        _exec_gravity(state, data)
    elif opcode == 0xA3:
        _exec_friction(state, data)
    elif opcode == 0xA8:
        _exec_rand_offset(state, data)
    elif opcode == 0xAB:
        _exec_scale_vel(state, data)
    elif opcode == 0xAC:
        _exec_scale_rand(state, data)
    elif opcode == 0xA9:
        _exec_modify_dir(state, data)
    elif opcode == 0xAD:
        pass  # PRIMENV_ON — rendering flag
    elif 0xAE <= opcode <= 0xB1:
        pass  # MIRROR modes — rendering flags
    elif opcode == 0xB4 or opcode == 0xB5:
        pass  # TEXINTERP — rendering flags
    elif opcode == 0xB6:
        _exec_rotate_rand(state, data)
    elif 0xC0 <= opcode <= 0xCF:
        _exec_set_primcol(state, data, opcode)
    elif 0xD0 <= opcode <= 0xDF:
        _exec_set_envcol(state, data, opcode)
    elif opcode == 0xED:
        _exec_rand_rotate(state, data)
    elif opcode == 0xF3:
        _exec_rotate_accel(state, data)
    elif opcode == 0xF5 or opcode == 0xF6:
        pass  # GEN_FLAG — generator flags, skip
    elif opcode == 0xF7:
        pass  # NO_ZCOMP — rendering flag
    elif opcode == 0xFA:
        _exec_loop_start(state, data)
    elif opcode == 0xFB:
        _exec_loop_end(state, data)
    elif opcode == 0xFC:
        state.jump_pos = state.cmd_pos
    elif opcode == 0xFD:
        state.cmd_pos = state.jump_pos
    else:
        # Unknown opcode — skip by reading args heuristically
        _skip_unknown(state, data, opcode)


# ---------------------------------------------------------------------------
# Opcode handlers
# ---------------------------------------------------------------------------

def _read_float(data, pos):
    if pos + 4 > len(data):
        return 0.0, len(data)
    val = struct.unpack_from('>f', data, pos)[0]
    return val, pos + 4


def _read_time(data, pos):
    if pos >= len(data):
        return 0, len(data)
    b = data[pos]
    pos += 1
    if b & 0x80:
        if pos >= len(data):
            return b & 0x7F, len(data)
        b2 = data[pos]
        pos += 1
        return ((b & 0x7F) << 8) | b2, pos
    return b, pos


def _read_u8(data, pos):
    if pos >= len(data):
        return 0, len(data)
    return data[pos], pos + 1


def _read_u16(data, pos):
    if pos + 2 > len(data):
        return 0, len(data)
    return struct.unpack_from('>H', data, pos)[0], pos + 2


def _exec_set_pos(state, data, opcode):
    if opcode & 1:
        state.position[0], state.cmd_pos = _read_float(data, state.cmd_pos)
    if opcode & 2:
        state.position[1], state.cmd_pos = _read_float(data, state.cmd_pos)
    if opcode & 4:
        state.position[2], state.cmd_pos = _read_float(data, state.cmd_pos)


def _exec_move(state, data, opcode):
    if opcode & 1:
        dx, state.cmd_pos = _read_float(data, state.cmd_pos)
        state.position[0] += dx
    if opcode & 2:
        dy, state.cmd_pos = _read_float(data, state.cmd_pos)
        state.position[1] += dy
    if opcode & 4:
        dz, state.cmd_pos = _read_float(data, state.cmd_pos)
        state.position[2] += dz


def _exec_set_vel(state, data, opcode):
    if opcode & 1:
        state.velocity[0], state.cmd_pos = _read_float(data, state.cmd_pos)
    if opcode & 2:
        state.velocity[1], state.cmd_pos = _read_float(data, state.cmd_pos)
    if opcode & 4:
        state.velocity[2], state.cmd_pos = _read_float(data, state.cmd_pos)


def _exec_accel(state, data, opcode):
    if opcode & 1:
        dv, state.cmd_pos = _read_float(data, state.cmd_pos)
        state.velocity[0] += dv
    if opcode & 2:
        dv, state.cmd_pos = _read_float(data, state.cmd_pos)
        state.velocity[1] += dv
    if opcode & 4:
        dv, state.cmd_pos = _read_float(data, state.cmd_pos)
        state.velocity[2] += dv


def _exec_scale(state, data):
    state.size_time, state.cmd_pos = _read_time(data, state.cmd_pos)
    state.size_target, state.cmd_pos = _read_float(data, state.cmd_pos)
    if state.size_time == 0:
        state.size = state.size_target


def _exec_scale_rand(state, data):
    state.size_time, state.cmd_pos = _read_time(data, state.cmd_pos)
    range_val, state.cmd_pos = _read_float(data, state.cmd_pos)
    state.size_target = state.size + range_val * _random.random()
    if state.size_time == 0:
        state.size = state.size_target


def _exec_gravity(state, data):
    state.gravity, state.cmd_pos = _read_float(data, state.cmd_pos)


def _exec_friction(state, data):
    state.friction, state.cmd_pos = _read_float(data, state.cmd_pos)


def _exec_rand_offset(state, data):
    dx, state.cmd_pos = _read_float(data, state.cmd_pos)
    dy, state.cmd_pos = _read_float(data, state.cmd_pos)
    dz, state.cmd_pos = _read_float(data, state.cmd_pos)
    state.position[0] += (2 * _random.random() - 1) * dx
    state.position[1] += (2 * _random.random() - 1) * dy
    state.position[2] += (2 * _random.random() - 1) * dz


def _exec_scale_vel(state, data):
    factor, state.cmd_pos = _read_float(data, state.cmd_pos)
    state.velocity[0] *= factor
    state.velocity[1] *= factor
    state.velocity[2] *= factor


def _exec_modify_dir(state, data):
    angle, state.cmd_pos = _read_float(data, state.cmd_pos)
    # Rotate velocity vector by angle around Y axis
    vx, vy, vz = state.velocity
    c, s = math.cos(angle), math.sin(angle)
    state.velocity[0] = vx * c - vz * s
    state.velocity[2] = vx * s + vz * c


def _exec_set_primcol(state, data, opcode):
    """SET_PRIMCOL (0xC0-0xCF): color interpolation target with RGBA channel flags."""
    # Resolve current interpolation first
    _finish_color_interp(state.prim_color, state.prim_target, state.prim_time)
    state.prim_time, state.cmd_pos = _read_time(data, state.cmd_pos)
    state.prim_target = list(state.prim_color)
    if opcode & 0x01:
        state.prim_target[0], state.cmd_pos = _read_u8(data, state.cmd_pos)
    if opcode & 0x02:
        state.prim_target[1], state.cmd_pos = _read_u8(data, state.cmd_pos)
    if opcode & 0x04:
        state.prim_target[2], state.cmd_pos = _read_u8(data, state.cmd_pos)
    if opcode & 0x08:
        state.prim_target[3], state.cmd_pos = _read_u8(data, state.cmd_pos)
    if state.prim_time == 0:
        state.prim_color = list(state.prim_target)


def _exec_set_envcol(state, data, opcode):
    """SET_ENVCOL (0xD0-0xDF): same pattern as SET_PRIMCOL."""
    _finish_color_interp(state.env_color, state.env_target, state.env_time)
    state.env_time, state.cmd_pos = _read_time(data, state.cmd_pos)
    state.env_target = list(state.env_color)
    if opcode & 0x01:
        state.env_target[0], state.cmd_pos = _read_u8(data, state.cmd_pos)
    if opcode & 0x02:
        state.env_target[1], state.cmd_pos = _read_u8(data, state.cmd_pos)
    if opcode & 0x04:
        state.env_target[2], state.cmd_pos = _read_u8(data, state.cmd_pos)
    if opcode & 0x08:
        state.env_target[3], state.cmd_pos = _read_u8(data, state.cmd_pos)
    if state.env_time == 0:
        state.env_color = list(state.env_target)


def _exec_rotate_rand(state, data):
    state.rot_time, state.cmd_pos = _read_time(data, state.cmd_pos)
    target, state.cmd_pos = _read_float(data, state.cmd_pos)
    state.rot_rate = target
    if state.rot_time == 0:
        state.rotation = target


def _exec_rand_rotate(state, data):
    base, state.cmd_pos = _read_float(data, state.cmd_pos)
    range_val, state.cmd_pos = _read_float(data, state.cmd_pos)
    _param, state.cmd_pos = _read_u8(data, state.cmd_pos)
    state.rotation = base + range_val * _random.random()


def _exec_rotate_accel(state, data):
    direction, state.cmd_pos = _read_u8(data, state.cmd_pos)
    rate, state.cmd_pos = _read_float(data, state.cmd_pos)
    accel, state.cmd_pos = _read_float(data, state.cmd_pos)
    time, state.cmd_pos = _read_time(data, state.cmd_pos)
    state.rot_rate = rate if direction else -rate
    state.rot_accel = accel
    state.rot_time = time


def _exec_loop_start(state, data):
    count, state.cmd_pos = _read_u8(data, state.cmd_pos)
    state.loop_count = count
    state.loop_pos = state.cmd_pos


def _exec_loop_end(state, data):
    state.loop_count -= 1
    if state.loop_count > 0:
        state.cmd_pos = state.loop_pos


def _skip_unknown(state, data, opcode):
    """Skip unknown opcodes by consuming their likely arguments.

    Most opcodes in the 0xA0-0xBF range read getTime + getFloat or
    u16 + u8 combinations. For truly unknown opcodes, skip conservatively.
    """
    if opcode in (0xA4, 0xA5, 0xB9):
        # SPAWN_PARTICLE / SPAWN_GENERATOR / SPAWN_PARTICLE_VEL — u16
        state.cmd_pos += 2
    elif opcode == 0xA6:
        # RAND_KILL_TIMER — u16 + u16
        state.cmd_pos += 4
    elif opcode == 0xA7:
        # RAND_KILL_CHANCE — u8
        state.cmd_pos += 1
    elif opcode == 0xAA:
        # SPAWN_RAND_REF — u16 + u16
        state.cmd_pos += 4
    elif opcode == 0xB2:
        pass  # APPLY_APPSRT — no args
    elif opcode == 0xB3:
        # ALPHA_CMP — getTime + u8 + u8 + u8
        _, state.cmd_pos = _read_time(data, state.cmd_pos)
        state.cmd_pos += 3
    elif opcode == 0xB7:
        state.cmd_pos += 1  # VEL_TO_JOINT — u8
    elif opcode == 0xB8:
        state.cmd_pos += 9  # FORCES_JOINT — float + float + u8
    elif opcode in (0xBA, 0xBB):
        state.cmd_pos += 4  # RAND_PRIMCOL/ENVCOL — 4 u8
    elif opcode == 0xBC:
        state.cmd_pos += 2  # SET_TEXTURE_IDX — u8 + u8
    elif opcode == 0xBD:
        state.cmd_pos += 8  # SET_SPEED — float + float
    elif opcode == 0xBE:
        state.cmd_pos += 12  # SCALE_VEL_AXIS — 3 floats
    elif opcode == 0xBF:
        state.cmd_pos += 1  # SET_JOINT — u8
    elif opcode == 0xE0:
        state.cmd_pos += 4  # RAND_COLORS — 4 u8
    elif opcode == 0xE1:
        state.cmd_pos += 1  # SET_CALLBACK — u8
    elif opcode == 0xE3:
        state.cmd_pos += 1  # SET_PALETTE — u8
    elif opcode in (0xE4, 0xE5):
        state.cmd_pos += 1  # FLIP_S/T — u8
    elif opcode == 0xE8:
        state.cmd_pos += 4  # SET_TRAIL — float
    elif opcode == 0xE9:
        # RAND_PRIMENV — complex variable length
        flags, state.cmd_pos = _read_u8(data, state.cmd_pos)
        state.cmd_pos += 1  # count byte
        if flags & 0x1: state.cmd_pos += 1
        if flags & 0x2: state.cmd_pos += 1
        if flags & 0x4: state.cmd_pos += 1
        if flags & 0x8: state.cmd_pos += 1
    elif opcode in (0xEA, 0xEB):
        # MAT_COLOR / AMB_COLOR — getTime + u8 + conditional
        _, state.cmd_pos = _read_time(data, state.cmd_pos)
        flags, state.cmd_pos = _read_u8(data, state.cmd_pos)
        if flags & 0x1: state.cmd_pos += 1
        if flags & 0x8: state.cmd_pos += 1
    elif opcode == 0xEC:
        state.cmd_pos += 5  # CUSTOM_FLOAT — u8 + float
    elif opcode in (0xEF, 0xF0):
        state.cmd_pos += 3  # SPAWN_GEN_FLAGS — u16 + u8
    elif opcode in (0xF1, 0xF2):
        state.cmd_pos += 2  # SPAWN_PARTICLE_REF — u16
    elif opcode == 0xF4:
        state.cmd_pos += 16  # GEN_DIR_BASE — 4 floats


# ---------------------------------------------------------------------------
# Physics and interpolation (run every frame)
# ---------------------------------------------------------------------------

def _apply_physics(state):
    """Apply gravity, friction, and velocity to position."""
    state.velocity[1] += state.gravity
    if state.friction != 1.0:
        state.velocity[0] *= state.friction
        state.velocity[1] *= state.friction
        state.velocity[2] *= state.friction
    state.position[0] += state.velocity[0]
    state.position[1] += state.velocity[1]
    state.position[2] += state.velocity[2]


def _interpolate_size(state):
    """Interpolate size toward target over time."""
    if state.size_time > 0:
        t = 1.0 / state.size_time
        state.size += (state.size_target - state.size) * t
        state.size_time -= 1
        if state.size_time == 0:
            state.size = state.size_target


def _interpolate_color(state):
    """Interpolate prim_color and env_color toward targets."""
    if state.prim_time > 0:
        state.prim_time -= 1
        if state.prim_time == 0:
            state.prim_color = list(state.prim_target)
        else:
            t = 1.0 / (state.prim_time + 1)
            for i in range(4):
                state.prim_color[i] = int(state.prim_color[i] +
                    (state.prim_target[i] - state.prim_color[i]) * t)

    if state.env_time > 0:
        state.env_time -= 1
        if state.env_time == 0:
            state.env_color = list(state.env_target)
        else:
            t = 1.0 / (state.env_time + 1)
            for i in range(4):
                state.env_color[i] = int(state.env_color[i] +
                    (state.env_target[i] - state.env_color[i]) * t)


def _interpolate_rotation(state):
    """Apply rotation rate and acceleration."""
    if state.rot_time > 0:
        state.rotation += state.rot_rate
        if state.rot_accel != 0.0:
            if state.rot_rate >= 0:
                state.rot_rate += state.rot_accel
            else:
                state.rot_rate -= state.rot_accel
        state.rot_time -= 1


def _finish_color_interp(color, target, time):
    """Snap color to target if interpolation was in progress."""
    if time > 0:
        for i in range(4):
            color[i] = target[i]
