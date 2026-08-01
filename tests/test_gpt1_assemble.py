"""Round-trip tests for the GPT1 bytecode assembler."""
import struct
import pytest

from shared.helpers.gpt1_commands import (
    disassemble, assemble, ParticleInstruction,
)


def _rt(command_bytes):
    """disassemble → assemble → disassemble must be semantically stable."""
    ins1 = disassemble(command_bytes)
    reasm = assemble(ins1)
    ins2 = disassemble(reasm)
    assert len(ins1) == len(ins2)
    for a, b in zip(ins1, ins2):
        assert a.mnemonic == b.mnemonic
        assert a.args == b.args
    return reasm, ins1


def test_lifetime_short():
    # 0x15 = LIFETIME frames=21 (low5)
    reasm, ins = _rt(bytes([0x15, 0xFE]))
    assert ins[0].mnemonic == 'LIFETIME'
    assert ins[0].args['frames'] == 0x15


def test_lifetime_extended():
    # 0x21 0x2C = LIFETIME extended, frames = (1<<8)|44 = 300
    reasm, ins = _rt(bytes([0x21, 0x2C, 0xFE]))
    assert ins[0].mnemonic == 'LIFETIME'
    assert ins[0].args['frames'] == 300


def test_lifetime_tex_short():
    # 0x43 0x07 = LIFETIME_TEX frames=3 texture=7
    reasm, ins = _rt(bytes([0x43, 0x07, 0xFE]))
    assert ins[0].mnemonic == 'LIFETIME_TEX'
    assert ins[0].args['frames'] == 3
    assert ins[0].args['texture'] == 7


def test_lifetime_tex_extended():
    # 0x61 0x2C 0x09 = LIFETIME_TEX extended frames=300 texture=9
    reasm, ins = _rt(bytes([0x61, 0x2C, 0x09, 0xFE]))
    assert ins[0].args['frames'] == 300
    assert ins[0].args['texture'] == 9


def test_set_pos_xyz():
    payload = struct.pack('>fff', 1.0, 2.0, 3.0)
    reasm, ins = _rt(bytes([0x87]) + payload + bytes([0xFE]))
    assert ins[0].mnemonic == 'SET_POS'
    assert ins[0].args == {'x': 1.0, 'y': 2.0, 'z': 3.0}


def test_set_pos_partial():
    # 0x82 = SET_POS y only
    payload = struct.pack('>f', 5.5)
    reasm, ins = _rt(bytes([0x82]) + payload + bytes([0xFE]))
    assert ins[0].args == {'y': 5.5}


def test_move():
    payload = struct.pack('>f', -1.0)
    reasm, ins = _rt(bytes([0x89]) + payload + bytes([0xFE]))
    assert ins[0].mnemonic == 'MOVE'
    assert ins[0].args == {'x': -1.0}


def test_set_vel_accel():
    for base, name in [(0x90, 'SET_VEL'), (0x98, 'ACCEL')]:
        payload = struct.pack('>f', 2.5)
        reasm, ins = _rt(bytes([base | 0x02]) + payload + bytes([0xFE]))
        assert ins[0].mnemonic == name
        assert ins[0].args == {'y': 2.5}


def test_set_primcol_all_channels():
    # 0xCF = SET_PRIMCOL rgba, time=0x10, r=1 g=2 b=3 a=4
    raw = bytes([0xCF, 0x10, 1, 2, 3, 4, 0xFE])
    reasm, ins = _rt(raw)
    assert ins[0].mnemonic == 'SET_PRIMCOL'
    assert ins[0].args == {'time': 0x10, 'r': 1, 'g': 2, 'b': 3, 'a': 4}


def test_set_envcol_partial():
    # 0xD5 = SET_ENVCOL r+b, time=0
    raw = bytes([0xD5, 0x00, 100, 200, 0xFE])
    reasm, ins = _rt(raw)
    assert ins[0].args == {'time': 0, 'r': 100, 'b': 200}


def test_scale_time_short():
    payload = struct.pack('>f', 0.5)
    raw = bytes([0xA0, 0x05]) + payload + bytes([0xFE])
    reasm, ins = _rt(raw)
    assert ins[0].mnemonic == 'SCALE'
    assert ins[0].args == {'time': 5, 'target': 0.5}


def test_scale_time_extended():
    # time > 0x7F uses 2-byte encoding: 0x80|(v>>8), v&0xFF
    payload = struct.pack('>f', 0.5)
    raw = bytes([0xA0, 0x81, 0x00]) + payload + bytes([0xFE])
    reasm, ins = _rt(raw)
    assert ins[0].args['time'] == 256


def test_simple_opcodes():
    cases = {
        0xA1: 'TEX_OFF',
        0xAD: 'PRIMENV_ON',
        0xAE: 'MIRROR_OFF',
        0xF5: 'GEN_FLAG_2000',
        0xF6: 'GEN_FLAG_1000',
        0xF7: 'NO_ZCOMP',
        0xFB: 'LOOP_END',
    }
    for opcode, name in cases.items():
        reasm, ins = _rt(bytes([opcode, 0xFE]))
        assert ins[0].mnemonic == name, f'opcode 0x{opcode:02X}'


def test_loop_start_and_end():
    raw = bytes([0xFA, 0x05, 0xFB, 0xFE])
    reasm, ins = _rt(raw)
    assert ins[0].mnemonic == 'LOOP_START'
    assert ins[0].args == {'count': 5}
    assert ins[1].mnemonic == 'LOOP_END'
    assert ins[2].mnemonic == 'EXIT'


def test_rand_primcol():
    raw = bytes([0xBA, 10, 20, 30, 40, 0xFE])
    reasm, ins = _rt(raw)
    assert ins[0].args == {'r': 10, 'g': 20, 'b': 30, 'a': 40}


def test_rand_rotate():
    payload = struct.pack('>ff', 0.1, 0.2) + bytes([0x03])
    raw = bytes([0xED]) + payload + bytes([0xFE])
    reasm, ins = _rt(raw)
    assert ins[0].mnemonic == 'RAND_ROTATE'
    assert ins[0].args == {'base': pytest.approx(0.1), 'range': pytest.approx(0.2), 'param': 3}


def test_rotate_rand():
    payload = bytes([0x04]) + struct.pack('>f', 1.5)
    raw = bytes([0xB6]) + payload + bytes([0xFE])
    reasm, ins = _rt(raw)
    assert ins[0].mnemonic == 'ROTATE_RAND'
    assert ins[0].args == {'time': 4, 'value': 1.5}


def test_scale_rand():
    # Two floats: the interpreter scales to base + range * rand01. Reading a
    # single operand desynchronises the rest of the stream.
    payload = bytes([0x03]) + struct.pack('>f', 1.0) + struct.pack('>f', 2.0)
    raw = bytes([0xAC]) + payload + bytes([0xFF])
    reasm, ins = _rt(raw)
    assert ins[0].mnemonic == 'SCALE_RAND'
    assert ins[0].args == {'time': 3, 'base': 1.0, 'range': 2.0}
    assert ins[1].mnemonic == 'EXIT'


def test_modify_dir():
    payload = struct.pack('>f', 0.75)
    raw = bytes([0xA9]) + payload + bytes([0xFE])
    reasm, ins = _rt(raw)
    assert ins[0].mnemonic == 'MODIFY_DIR'
    assert ins[0].args == {'value': pytest.approx(0.75)}


def test_exit_is_canonicalized_to_ff():
    # Both 0xFE and 0xFF dispatch to the interpreter's exit handler; every
    # game-authored stream terminates with 0xFF, so the assembler emits that.
    for term in (0xFE, 0xFF):
        reasm, ins = _rt(bytes([0xA1, term]))
        assert ins[-1].mnemonic == 'EXIT'
        assert reasm[-1] == 0xFF


def test_assemble_raises_on_unknown_mnemonic():
    ins = [ParticleInstruction(offset=0, opcode=0, mnemonic='NOT_A_REAL_OPCODE', args={})]
    with pytest.raises(ValueError, match='unknown mnemonic'):
        assemble(ins)


def test_real_models_semantic_roundtrip():
    """Every generator in every model with GPT1 must survive disassemble → assemble → disassemble."""
    import os
    models_dir = '/Users/stars/Documents/Projects/DAT plugin/models'
    if not os.path.isdir(models_dir):
        pytest.skip('Real models not available')
    from shared.helpers.pkx import PKXContainer
    from shared.helpers.gpt1 import GPT1File
    names = ['ghos', 'lizardon', 'fire', 'freezer', 'showers']
    for name in names:
        path = os.path.join(models_dir, f'{name}.pkx')
        if not os.path.exists(path):
            continue
        container = PKXContainer.from_file(path)
        if not container.gpt1_data:
            continue
        gpt = GPT1File.from_bytes(container.gpt1_data)
        for i, gen in enumerate(gpt.ptl.generators):
            ins1 = disassemble(gen.command_bytes)
            reasm = assemble(ins1)
            ins2 = disassemble(reasm)
            assert len(ins1) == len(ins2), f'{name} gen {i}'
            for a, b in zip(ins1, ins2):
                assert a.mnemonic == b.mnemonic, f'{name} gen {i}'
                assert a.args == b.args, f'{name} gen {i}'


def _stream(*instructions):
    """Assemble a synthetic stream, then hand back its bytes."""
    return bytes(assemble([ParticleInstruction(offset=0, opcode=0, mnemonic=m, args=a)
                           for m, a in instructions]))


def test_operand_widths_keep_the_stream_in_sync():
    """A mis-sized operand desynchronises everything after it.

    This is the failure the corpus showed before SCALE_RAND's second float was
    recovered: the decoder stopped inside a float and read its bytes as
    further instructions, inventing 8000-frame lifetimes and out-of-range
    texture indices. Assembling a known stream and disassembling it back is
    the cheap standing check that every operand width still lines up.
    """
    known = [
        ('SCALE_RAND', {'time': 0, 'base': 2.0, 'range': 1.0}),
        ('SCALE', {'time': 40, 'target': 0.5}),
        ('LIFETIME', {'frames': 30}),
        ('SET_PRIMCOL', {'time': 3, 'r': 255, 'g': 255, 'b': 10, 'a': 255}),
        ('LIFETIME', {'frames': 5}),
        ('EXIT', {}),
    ]
    decoded = disassemble(_stream(*known))
    assert [(i.mnemonic, i.args) for i in decoded] == known


def test_scale_rand_second_float_is_not_read_as_opcodes():
    """The exact regression: 0x3F800000 (1.0) must stay an operand."""
    raw = (bytes([0xAC, 0x00]) + struct.pack('>f', 2.0) + struct.pack('>f', 1.0)
           + bytes([0xFF]))
    decoded = disassemble(raw)
    assert [i.mnemonic for i in decoded] == ['SCALE_RAND', 'EXIT']
    assert decoded[0].args['range'] == 1.0
