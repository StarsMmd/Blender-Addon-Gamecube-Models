"""Opcode ↔ geometry-nodes sub-graph translation for GPT1 particles.

Each GPT1 instruction is represented in a generator's Geometry Node tree as
a single NodeFrame carrying the mnemonic in `name`, an `age_threshold`
custom property (cumulative age at which the instruction fires), and the
opcode `args` dict stored as JSON on the frame's `label`. This is the
authoritative record that the exporter reads back.

The behavioral node graph (the simulation zone that actually moves the
particles) is built alongside but its contents do NOT encode instructions
— that responsibility lives exclusively on the per-instruction NodeFrames.

Naming:
    gpt1_{MNEMONIC}_i{instruction_index}     — one frame per instruction
    gpt1_header                              — header-fields frame

The `instruction_index` is the position of the instruction in the generator's
original bytecode order (preserves duplicates and interleaving). Loops are
NOT unrolled — LOOP_START and LOOP_END appear as their own frames.
"""
from __future__ import annotations
import json

try:
    from .....shared.helpers.gpt1_commands import ParticleInstruction
except (ImportError, SystemError):
    from shared.helpers.gpt1_commands import ParticleInstruction


# Frame prefix used for plugin-created per-instruction nodes.
INSTRUCTION_NODE_PREFIX = 'gpt1_'

# Supported mnemonics in Phase 1 — anything not in this set raises on export.
SUPPORTED_MNEMONICS = frozenset([
    'LIFETIME', 'LIFETIME_TEX',
    'SET_PRIMCOL', 'RAND_PRIMCOL',
    'SET_ENVCOL',
    'SCALE', 'SCALE_RAND',
    'RAND_ROTATE', 'ROTATE_RAND',
    'TEX_OFF',
    'SET_POS', 'SET_VEL', 'ACCEL',
    'MODIFY_DIR',
    'PRIMENV_ON', 'GEN_FLAG_2000',
    'LOOP_START', 'LOOP_END',
    'EXIT',
])


def instruction_node_name(mnemonic: str, index: int) -> str:
    """Return the frame-node name for a given (mnemonic, instruction_index).

    In: mnemonic (str); index (int).
    Out: str — '{INSTRUCTION_NODE_PREFIX}{mnemonic}_iNNN'.
    """
    return f'{INSTRUCTION_NODE_PREFIX}{mnemonic}_i{index:03d}'


def serialize_args(args: dict) -> str:
    """Serialize an args dict as a stable JSON string for ``node.label``.

    In: args (dict, JSON-serialisable).
    Out: str, JSON with sorted keys and compact separators.
    """
    return json.dumps(args, sort_keys=True, separators=(',', ':'))


def deserialize_args(label: str) -> dict:
    """Parse an args dict from a ``node.label`` that was set by serialize_args.

    In: label (str).
    Out: dict; empty on missing or malformed JSON.
    """
    if not label:
        return {}
    try:
        return json.loads(label)
    except json.JSONDecodeError:
        return {}


def parse_instruction_node_name(name: str):
    """Parse ``gpt1_MNEMONIC_iNNN`` → (mnemonic, index) or None.

    In: name (str).
    Out: tuple[str, int] | None.
    """
    if not name.startswith(INSTRUCTION_NODE_PREFIX):
        return None
    rest = name[len(INSTRUCTION_NODE_PREFIX):]
    # Split into mnemonic and _iNNN suffix
    i_pos = rest.rfind('_i')
    if i_pos < 0:
        return None
    mnemonic = rest[:i_pos]
    try:
        index = int(rest[i_pos + 2:])
    except ValueError:
        return None
    return mnemonic, index


def build_instruction_frame(tree, instruction: ParticleInstruction,
                            index: int, age_threshold: int):
    """Add one NodeFrame representing a bytecode instruction to ``tree``.

    In: tree (bpy.types.GeometryNodeTree); instruction (ParticleInstruction);
        index (int, position in the generator's instruction list);
        age_threshold (int, cumulative age in frames at which it fires).
    Out: bpy.types.NodeFrame — the created frame, already added to ``tree``.
    """
    frame = tree.nodes.new('NodeFrame')
    frame.name = instruction_node_name(instruction.mnemonic, index)
    frame.label = serialize_args(instruction.args)
    frame['age_threshold'] = int(age_threshold)
    frame['mnemonic'] = instruction.mnemonic
    frame['instr_index'] = int(index)
    frame.use_custom_color = True
    frame.color = _color_for_mnemonic(instruction.mnemonic)
    # Stagger frames so they're visually readable in the node editor.
    frame.location = (index * 220, 0)
    frame.width = 200
    frame.height = 80
    return frame


def read_instruction_frames(tree):
    """Walk a GeometryNodeTree and recover the bytecode instruction list.

    In: tree (bpy.types.GeometryNodeTree).
    Out: list[ParticleInstruction] — in instruction_index (bytecode) order.
         ``offset``, ``opcode``, and ``raw_bytes`` are placeholders (0/b'')
         because they aren't recoverable from the Blender-side representation.
    """
    frames = []
    for node in tree.nodes:
        if node.bl_idname != 'NodeFrame':
            continue
        parsed = parse_instruction_node_name(node.name)
        if parsed is None:
            continue
        mnemonic, idx = parsed
        args = deserialize_args(node.label)
        frames.append((idx, mnemonic, args))

    frames.sort(key=lambda t: t[0])
    instructions = []
    for _, mnemonic, args in frames:
        instructions.append(ParticleInstruction(
            offset=0,
            opcode=0,
            mnemonic=mnemonic,
            args=args,
            raw_bytes=b'',
        ))
    return instructions


def _color_for_mnemonic(mnemonic):
    """Pick a deterministic RGB hint color for a NodeFrame by mnemonic family.

    In: mnemonic (str).
    Out: tuple[float, float, float] — RGB in 0..1 (default grey for unknowns).
    """
    palette = {
        'LIFETIME':       (0.25, 0.25, 0.25),
        'LIFETIME_TEX':   (0.25, 0.30, 0.40),
        'SET_PRIMCOL':    (0.50, 0.15, 0.15),
        'RAND_PRIMCOL':   (0.60, 0.20, 0.20),
        'SET_ENVCOL':     (0.15, 0.30, 0.50),
        'SCALE':          (0.20, 0.40, 0.20),
        'SCALE_RAND':     (0.25, 0.45, 0.25),
        'RAND_ROTATE':    (0.45, 0.35, 0.15),
        'ROTATE_RAND':    (0.45, 0.35, 0.15),
        'LOOP_START':     (0.35, 0.10, 0.40),
        'LOOP_END':       (0.35, 0.10, 0.40),
        'EXIT':           (0.10, 0.10, 0.10),
    }
    return palette.get(mnemonic, (0.30, 0.30, 0.30))


def compute_age_thresholds(instructions):
    """For each instruction, compute its cumulative age threshold in frames.

    LIFETIME and LIFETIME_TEX advance the virtual clock by their `frames`
    arg; every other opcode fires at the current threshold without advancing.

    Returns:
        list[int] — same length as `instructions`.
    """
    thresholds = []
    cursor = 0
    for ins in instructions:
        thresholds.append(cursor)
        if ins.mnemonic in ('LIFETIME', 'LIFETIME_TEX'):
            cursor += int(ins.args.get('frames', 0))
    return thresholds
