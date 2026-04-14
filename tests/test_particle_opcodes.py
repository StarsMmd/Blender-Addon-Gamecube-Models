"""Tests for the particle opcode frame encoding and age-threshold computation."""
import pytest

from importer.phases.build_blender.helpers.particle_opcodes import (
    instruction_node_name, parse_instruction_node_name,
    serialize_args, deserialize_args,
    compute_age_thresholds, SUPPORTED_MNEMONICS,
)
from shared.helpers.gpt1_commands import ParticleInstruction


def _ins(mnemonic, **args):
    return ParticleInstruction(offset=0, opcode=0, mnemonic=mnemonic, args=args)


def test_instruction_node_name_is_stable():
    assert instruction_node_name('SET_PRIMCOL', 5) == 'gpt1_SET_PRIMCOL_i005'
    assert instruction_node_name('LIFETIME', 0) == 'gpt1_LIFETIME_i000'


def test_parse_instruction_node_name_roundtrip():
    name = instruction_node_name('LIFETIME_TEX', 42)
    mnemonic, idx = parse_instruction_node_name(name)
    assert mnemonic == 'LIFETIME_TEX'
    assert idx == 42


def test_parse_ignores_unrelated_nodes():
    assert parse_instruction_node_name('NodeFrame.001') is None
    assert parse_instruction_node_name('Group Input') is None


def test_args_roundtrip_through_json():
    args = {'frames': 60, 'texture': 3}
    decoded = deserialize_args(serialize_args(args))
    assert decoded == args


def test_args_deserialize_empty_label():
    assert deserialize_args('') == {}


def test_args_deserialize_invalid_json_returns_empty():
    assert deserialize_args('not-json') == {}


def test_compute_age_thresholds_lifetime_chains():
    instructions = [
        _ins('LIFETIME', frames=10),
        _ins('SET_PRIMCOL', time=0, r=1),
        _ins('LIFETIME', frames=20),
        _ins('SCALE', time=5, target=2.0),
        _ins('EXIT'),
    ]
    thresholds = compute_age_thresholds(instructions)
    assert thresholds == [0, 10, 10, 30, 30]


def test_compute_age_thresholds_lifetime_tex_advances_clock():
    instructions = [
        _ins('LIFETIME_TEX', frames=15, texture=0),
        _ins('LIFETIME_TEX', frames=5, texture=1),
    ]
    assert compute_age_thresholds(instructions) == [0, 15]


def test_supported_mnemonics_contains_all_19():
    expected_core = {
        'LIFETIME', 'LIFETIME_TEX',
        'SET_PRIMCOL', 'RAND_PRIMCOL', 'SET_ENVCOL',
        'SCALE', 'SCALE_RAND',
        'RAND_ROTATE', 'ROTATE_RAND',
        'TEX_OFF', 'SET_POS', 'SET_VEL', 'ACCEL',
        'MODIFY_DIR', 'PRIMENV_ON', 'GEN_FLAG_2000',
        'LOOP_START', 'LOOP_END', 'EXIT',
    }
    assert expected_core.issubset(SUPPORTED_MNEMONICS)


def test_real_models_all_use_only_supported_opcodes():
    """Every opcode actually used by the priority models must be in the Phase 1 scope."""
    import os
    from shared.helpers.pkx import PKXContainer
    from shared.helpers.gpt1 import GPT1File
    from shared.helpers.gpt1_commands import disassemble

    models_dir = '/Users/stars/Documents/Projects/DAT plugin/models'
    if not os.path.isdir(models_dir):
        pytest.skip('Real models not available')

    names = ['ghos', 'lizardon', 'fire', 'freezer', 'showers']
    unsupported = set()
    for name in names:
        path = os.path.join(models_dir, f'{name}.pkx')
        if not os.path.exists(path):
            continue
        container = PKXContainer.from_file(path)
        if not container.gpt1_data:
            continue
        gpt = GPT1File.from_bytes(container.gpt1_data)
        for gen in gpt.ptl.generators:
            for ins in disassemble(gen.command_bytes):
                if ins.mnemonic not in SUPPORTED_MNEMONICS:
                    unsupported.add(ins.mnemonic)

    assert not unsupported, (
        "The following opcodes appear in real priority models but are not in "
        "SUPPORTED_MNEMONICS: " + ', '.join(sorted(unsupported))
    )
