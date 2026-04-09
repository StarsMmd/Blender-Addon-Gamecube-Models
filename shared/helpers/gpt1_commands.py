"""GPT1 particle command bytecode disassembler.

Decodes the variable-length command sequences embedded in GPT1 generator
definitions into structured instruction lists.

See documentation/file_formats.md for the full opcode table.
"""
import struct
from dataclasses import dataclass, field


@dataclass
class ParticleInstruction:
    """One decoded particle command."""
    offset: int             # Byte offset in the command stream
    opcode: int             # Raw opcode byte
    mnemonic: str           # Human-readable name
    args: dict = field(default_factory=dict)  # Named arguments
    raw_bytes: bytes = b''  # Complete raw bytes for this instruction


def _read_float(data, pos):
    """Read a big-endian float from data at pos. Returns (value, new_pos)."""
    if pos + 4 > len(data):
        return 0.0, len(data)
    val = struct.unpack_from('>f', data, pos)[0]
    return val, pos + 4


def _read_time(data, pos):
    """Read a variable-length time value from the command stream.

    Matches the game's getTime function: reads 1 byte. If bit 7 is set,
    reads a second byte and combines into a 15-bit value:
        byte0 & 0x80 == 0: result = byte0 (0-127)
        byte0 & 0x80 != 0: result = ((byte0 & 0x7F) << 8) | byte1 (0-32767)

    Returns (value, new_pos).
    """
    if pos >= len(data):
        return 0, len(data)
    byte0 = data[pos]
    pos += 1
    if byte0 & 0x80:
        if pos >= len(data):
            return byte0 & 0x7F, len(data)
        byte1 = data[pos]
        pos += 1
        return ((byte0 & 0x7F) << 8) | byte1, pos
    return byte0, pos


def _read_u16(data, pos):
    """Read a big-endian u16 from data at pos. Returns (value, new_pos)."""
    if pos + 2 > len(data):
        return 0, len(data)
    val = struct.unpack_from('>H', data, pos)[0]
    return val, pos + 2


def _read_u8(data, pos):
    """Read a u8 from data at pos. Returns (value, new_pos)."""
    if pos >= len(data):
        return 0, len(data)
    return data[pos], pos + 1


def disassemble(command_bytes):
    """Disassemble particle command bytecode into instruction list.

    Args:
        command_bytes: Raw bytecode bytes from a GeneratorDef.

    Returns:
        list[ParticleInstruction]
    """
    instructions = []
    data = command_bytes
    pos = 0

    while pos < len(data):
        start = pos
        opcode, pos = _read_u8(data, pos)
        args = {}

        if opcode < 0x80:
            # 0x00-0x7F: Lifetime + texture select
            mnemonic, args, pos = _decode_lifetime(opcode, data, pos)

        elif opcode <= 0x87:
            # 0x80-0x87: Set position
            mnemonic = "SET_POS"
            args, pos = _decode_xyz_floats(opcode, data, pos)

        elif opcode <= 0x8F:
            # 0x88-0x8F: Move (add to position)
            mnemonic = "MOVE"
            args, pos = _decode_xyz_floats(opcode, data, pos)

        elif opcode <= 0x97:
            # 0x90-0x97: Set velocity
            mnemonic = "SET_VEL"
            args, pos = _decode_xyz_floats(opcode, data, pos)

        elif opcode <= 0x9F:
            # 0x98-0x9F: Accelerate
            mnemonic = "ACCEL"
            args, pos = _decode_xyz_floats(opcode, data, pos)

        elif opcode == 0xA0:
            mnemonic = "SCALE"
            args['time'], pos = _read_time(data, pos)
            args['target'], pos = _read_float(data, pos)

        elif opcode == 0xA1:
            mnemonic = "TEX_OFF"

        elif opcode == 0xA2:
            mnemonic = "GRAVITY"
            args['value'], pos = _read_float(data, pos)

        elif opcode == 0xA3:
            mnemonic = "FRICTION"
            args['value'], pos = _read_float(data, pos)

        elif opcode == 0xA4:
            mnemonic = "SPAWN_PARTICLE"
            args['id'], pos = _read_u16(data, pos)

        elif opcode == 0xA5:
            mnemonic = "SPAWN_GENERATOR"
            args['id'], pos = _read_u16(data, pos)

        elif opcode == 0xA6:
            mnemonic = "RAND_KILL_TIMER"
            args['base'], pos = _read_u16(data, pos)
            args['range'], pos = _read_u16(data, pos)

        elif opcode == 0xA7:
            mnemonic = "RAND_KILL_CHANCE"
            args['chance'], pos = _read_u8(data, pos)

        elif opcode == 0xA8:
            mnemonic = "RAND_OFFSET"
            args['x'], pos = _read_float(data, pos)
            args['y'], pos = _read_float(data, pos)
            args['z'], pos = _read_float(data, pos)

        elif opcode == 0xA9:
            mnemonic = "MODIFY_DIR"
            args['value'], pos = _read_float(data, pos)

        elif opcode == 0xAA:
            mnemonic = "SPAWN_RAND_REF"
            args['base'], pos = _read_u16(data, pos)
            args['count'], pos = _read_u16(data, pos)

        elif opcode == 0xAB:
            mnemonic = "SCALE_VEL"
            args['factor'], pos = _read_float(data, pos)

        elif opcode == 0xAC:
            mnemonic = "SCALE_RAND"
            args['time'], pos = _read_time(data, pos)
            args['range'], pos = _read_float(data, pos)

        elif opcode == 0xAD:
            mnemonic = "PRIMENV_ON"
        elif opcode == 0xAE:
            mnemonic = "MIRROR_OFF"
        elif opcode == 0xAF:
            mnemonic = "MIRROR_S"
        elif opcode == 0xB0:
            mnemonic = "MIRROR_T"
        elif opcode == 0xB1:
            mnemonic = "MIRROR_ST"
        elif opcode == 0xB2:
            mnemonic = "APPLY_APPSRT"

        elif opcode == 0xB3:
            mnemonic = "ALPHA_CMP"
            args['time'], pos = _read_time(data, pos)
            args['mode'], pos = _read_u8(data, pos)
            args['param1'], pos = _read_u8(data, pos)
            args['param2'], pos = _read_u8(data, pos)

        elif opcode == 0xB4:
            mnemonic = "TEXINTERP_NEAR"
        elif opcode == 0xB5:
            mnemonic = "TEXINTERP_LINEAR"

        elif opcode == 0xB6:
            mnemonic = "ROTATE_RAND"
            args['time'], pos = _read_time(data, pos)
            args['value'], pos = _read_float(data, pos)

        elif opcode == 0xB7:
            mnemonic = "VEL_TO_JOINT"
            args['joint'], pos = _read_u8(data, pos)

        elif opcode == 0xB8:
            mnemonic = "FORCES_JOINT"
            args['gravity'], pos = _read_float(data, pos)
            args['friction'], pos = _read_float(data, pos)
            args['joint'], pos = _read_u8(data, pos)

        elif opcode == 0xB9:
            mnemonic = "SPAWN_PARTICLE_VEL"
            args['id'], pos = _read_u16(data, pos)

        elif opcode == 0xBA:
            mnemonic = "RAND_PRIMCOL"
            args['r'], pos = _read_u8(data, pos)
            args['g'], pos = _read_u8(data, pos)
            args['b'], pos = _read_u8(data, pos)
            args['a'], pos = _read_u8(data, pos)

        elif opcode == 0xBB:
            mnemonic = "RAND_ENVCOL"
            args['r'], pos = _read_u8(data, pos)
            args['g'], pos = _read_u8(data, pos)
            args['b'], pos = _read_u8(data, pos)
            args['a'], pos = _read_u8(data, pos)

        elif opcode == 0xBC:
            mnemonic = "SET_TEXTURE_IDX"
            args['base'], pos = _read_u8(data, pos)
            args['range'], pos = _read_u8(data, pos)

        elif opcode == 0xBD:
            mnemonic = "SET_SPEED"
            args['base'], pos = _read_float(data, pos)
            args['range'], pos = _read_float(data, pos)

        elif opcode == 0xBE:
            mnemonic = "SCALE_VEL_AXIS"
            args['x'], pos = _read_float(data, pos)
            args['y'], pos = _read_float(data, pos)
            args['z'], pos = _read_float(data, pos)

        elif opcode == 0xBF:
            mnemonic = "SET_JOINT"
            args['id'], pos = _read_u8(data, pos)

        elif 0xC0 <= opcode <= 0xCF:
            mnemonic = "SET_PRIMCOL"
            args, pos = _decode_color_target(opcode, data, pos)

        elif 0xD0 <= opcode <= 0xDF:
            mnemonic = "SET_ENVCOL"
            args, pos = _decode_color_target(opcode, data, pos)

        elif opcode == 0xE0:
            mnemonic = "RAND_COLORS"
            args['r'], pos = _read_u8(data, pos)
            args['g'], pos = _read_u8(data, pos)
            args['b'], pos = _read_u8(data, pos)
            args['a'], pos = _read_u8(data, pos)

        elif opcode == 0xE1:
            mnemonic = "SET_CALLBACK"
            args['id'], pos = _read_u8(data, pos)

        elif opcode == 0xE2:
            mnemonic = "TEXEDGE_ON"

        elif opcode == 0xE3:
            mnemonic = "SET_PALETTE"
            args['id'], pos = _read_u8(data, pos)

        elif opcode == 0xE4:
            mnemonic = "FLIP_S"
            args['mode'], pos = _read_u8(data, pos)

        elif opcode == 0xE5:
            mnemonic = "FLIP_T"
            args['mode'], pos = _read_u8(data, pos)

        elif opcode == 0xE6:
            mnemonic = "DIRVEC_ON"
        elif opcode == 0xE7:
            mnemonic = "DIRVEC_OFF"

        elif opcode == 0xE8:
            mnemonic = "SET_TRAIL"
            args['length'], pos = _read_float(data, pos)

        elif opcode == 0xE9:
            mnemonic = "RAND_PRIMENV"
            args['flags'], pos = _read_u8(data, pos)
            args['count'], pos = _read_u8(data, pos)
            flags = args['flags']
            if flags & 0x1:
                args['r_delta'], pos = _read_u8(data, pos)
            if flags & 0x2:
                args['g_delta'], pos = _read_u8(data, pos)
            if flags & 0x4:
                args['b_delta'], pos = _read_u8(data, pos)
            if flags & 0x8:
                args['a_delta'], pos = _read_u8(data, pos)

        elif opcode == 0xEA:
            mnemonic = "MAT_COLOR"
            args['time'], pos = _read_time(data, pos)
            args['flags'], pos = _read_u8(data, pos)
            flags = args['flags']
            if flags & 0x1:
                args['rgb'], pos = _read_u8(data, pos)
            if flags & 0x8:
                args['alpha'], pos = _read_u8(data, pos)

        elif opcode == 0xEB:
            mnemonic = "AMB_COLOR"
            args['time'], pos = _read_time(data, pos)
            args['flags'], pos = _read_u8(data, pos)
            flags = args['flags']
            if flags & 0x1:
                args['rgb'], pos = _read_u8(data, pos)
            if flags & 0x8:
                args['alpha'], pos = _read_u8(data, pos)

        elif opcode == 0xEC:
            mnemonic = "CUSTOM_FLOAT"
            args['index'], pos = _read_u8(data, pos)
            args['value'], pos = _read_float(data, pos)

        elif opcode == 0xED:
            mnemonic = "RAND_ROTATE"
            args['base'], pos = _read_float(data, pos)
            args['range'], pos = _read_float(data, pos)
            args['param'], pos = _read_u8(data, pos)

        elif opcode == 0xEF:
            mnemonic = "SPAWN_GEN_FLAGS"
            args['id'], pos = _read_u16(data, pos)
            args['flags'], pos = _read_u8(data, pos)

        elif opcode == 0xF0:
            mnemonic = "SPAWN_GEN_REF_FLAGS"
            args['ref'], pos = _read_u16(data, pos)
            args['flags'], pos = _read_u8(data, pos)

        elif opcode == 0xF1:
            mnemonic = "SPAWN_PARTICLE_REF"
            args['ref'], pos = _read_u16(data, pos)

        elif opcode == 0xF2:
            mnemonic = "SPAWN_PARTICLE_REF_VEL"
            args['ref'], pos = _read_u16(data, pos)

        elif opcode == 0xF3:
            mnemonic = "ROTATE_ACCEL"
            args['direction'], pos = _read_u8(data, pos)
            args['rate'], pos = _read_float(data, pos)
            args['accel'], pos = _read_float(data, pos)
            args['time'], pos = _read_time(data, pos)

        elif opcode == 0xF4:
            mnemonic = "GEN_DIR_BASE"
            args['f1'], pos = _read_float(data, pos)
            args['f2'], pos = _read_float(data, pos)
            args['f3'], pos = _read_float(data, pos)
            args['f4'], pos = _read_float(data, pos)

        elif opcode == 0xF5:
            mnemonic = "GEN_FLAG_2000"
        elif opcode == 0xF6:
            mnemonic = "GEN_FLAG_1000"
        elif opcode == 0xF7:
            mnemonic = "NO_ZCOMP"

        elif opcode == 0xFA:
            mnemonic = "LOOP_START"
            args['count'], pos = _read_u8(data, pos)

        elif opcode == 0xFB:
            mnemonic = "LOOP_END"

        elif opcode == 0xFC:
            mnemonic = "SAVE_JUMP"

        elif opcode == 0xFD:
            mnemonic = "JUMP"

        elif opcode in (0xFE, 0xFF):
            mnemonic = "EXIT"

        else:
            mnemonic = "UNKNOWN_0x%02X" % opcode

        raw = data[start:pos]
        instructions.append(ParticleInstruction(
            offset=start,
            opcode=opcode,
            mnemonic=mnemonic,
            args=args,
            raw_bytes=bytes(raw),
        ))

        # Stop after EXIT
        if opcode in (0xFE, 0xFF):
            break

    return instructions


# ---------------------------------------------------------------------------
# Decode helpers
# ---------------------------------------------------------------------------

def _decode_lifetime(opcode, data, pos):
    """Decode a 0x00-0x7F lifetime/texture command."""
    args = {}
    low5 = opcode & 0x1F
    has_extended = (opcode & 0x20) != 0
    has_texture = (opcode & 0x40) != 0

    if has_extended:
        ext_byte, pos = _read_u8(data, pos)
        args['frames'] = (low5 << 8) | ext_byte
    else:
        args['frames'] = low5

    if has_texture:
        args['texture'], pos = _read_u8(data, pos)

    mnemonic = "LIFETIME"
    if has_texture:
        mnemonic = "LIFETIME_TEX"

    return mnemonic, args, pos


def _decode_xyz_floats(opcode, data, pos):
    """Decode axis-flagged float arguments (bits 0-2 = X,Y,Z)."""
    args = {}
    if opcode & 0x01:
        args['x'], pos = _read_float(data, pos)
    if opcode & 0x02:
        args['y'], pos = _read_float(data, pos)
    if opcode & 0x04:
        args['z'], pos = _read_float(data, pos)
    return args, pos


def _decode_color_target(opcode, data, pos):
    """Decode a color target command (0xCn or 0xDn, bits 0-3 = RGBA flags)."""
    args = {}
    args['time'], pos = _read_time(data, pos)
    if opcode & 0x01:
        args['r'], pos = _read_u8(data, pos)
    if opcode & 0x02:
        args['g'], pos = _read_u8(data, pos)
    if opcode & 0x04:
        args['b'], pos = _read_u8(data, pos)
    if opcode & 0x08:
        args['a'], pos = _read_u8(data, pos)
    return args, pos


def format_instructions(instructions):
    """Format instruction list as human-readable text.

    Args:
        instructions: list[ParticleInstruction]

    Returns:
        str — multi-line disassembly listing.
    """
    lines = []
    for inst in instructions:
        args_str = ', '.join(
            '%s=%s' % (k, ('%.4f' % v if isinstance(v, float) else str(v)))
            for k, v in inst.args.items()
        )
        hex_str = inst.raw_bytes.hex()
        lines.append('%04X: %-24s %-40s [%s]' % (
            inst.offset, inst.mnemonic, args_str, hex_str))
    return '\n'.join(lines)
