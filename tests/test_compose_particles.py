"""Tests for IRParticleSystem → GPT1 bytes composition."""
import pytest

from exporter.phases.compose.helpers.particles import compose_particles
from shared.IR.particles import (
    IRParticleSystem, IRParticleGenerator, IRParticleTexture,
)
from shared.helpers.gpt1 import GPT1File
from shared.helpers.gpt1_commands import ParticleInstruction, disassemble


def _ins(mnemonic, **args):
    return ParticleInstruction(offset=0, opcode=0, mnemonic=mnemonic, args=args)


def _generator(instructions, lifetime=120, max_particles=10, flags=0, gen_type=0, params=None):
    return IRParticleGenerator(
        gen_type=gen_type,
        lifetime=lifetime,
        max_particles=max_particles,
        flags=flags,
        params=params or (0.0,) * 12,
        instructions=instructions,
    )


def test_empty_particle_system_emits_empty_bytes():
    assert compose_particles(IRParticleSystem()) == b''
    assert compose_particles(None) == b''


def test_single_generator_roundtrip():
    ir = IRParticleSystem(generators=[
        _generator([
            _ins('LIFETIME', frames=30),
            _ins('SET_PRIMCOL', time=0, r=255, g=128, b=64, a=255),
            _ins('EXIT'),
        ]),
    ])
    blob = compose_particles(ir)
    assert blob
    gpt1 = GPT1File.from_bytes(blob)
    assert len(gpt1.ptl.generators) == 1

    # Re-disassemble the bytecode and check the instructions match.
    recovered = disassemble(gpt1.ptl.generators[0].command_bytes)
    assert [i.mnemonic for i in recovered] == ['LIFETIME', 'SET_PRIMCOL', 'EXIT']
    assert recovered[0].args == {'frames': 30}
    assert recovered[1].args == {'time': 0, 'r': 255, 'g': 128, 'b': 64, 'a': 255}


def test_multiple_generators_preserved():
    ir = IRParticleSystem(generators=[
        _generator([_ins('LIFETIME', frames=5), _ins('EXIT')], lifetime=60, max_particles=8),
        _generator([_ins('LIFETIME', frames=10), _ins('EXIT')], lifetime=120, max_particles=16),
    ])
    blob = compose_particles(ir)
    gpt1 = GPT1File.from_bytes(blob)
    assert len(gpt1.ptl.generators) == 2
    assert gpt1.ptl.generators[0].max_particles == 8
    assert gpt1.ptl.generators[1].max_particles == 16


def test_ref_ids_default_to_generator_indices():
    ir = IRParticleSystem(generators=[
        _generator([_ins('EXIT')]),
        _generator([_ins('EXIT')]),
        _generator([_ins('EXIT')]),
    ])
    blob = compose_particles(ir)
    gpt1 = GPT1File.from_bytes(blob)
    assert gpt1.ref_ids == [0, 1, 2]


def test_explicit_ref_ids_preserved():
    ir = IRParticleSystem(
        generators=[_generator([_ins('EXIT')]), _generator([_ins('EXIT')])],
        ref_ids=[42, 17],
    )
    blob = compose_particles(ir)
    gpt1 = GPT1File.from_bytes(blob)
    assert gpt1.ref_ids == [42, 17]


def test_params_preserved_through_roundtrip():
    params = (1.0, 2.5, 3.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    ir = IRParticleSystem(generators=[
        _generator([_ins('EXIT')], params=params, gen_type=7, flags=0xABCD),
    ])
    blob = compose_particles(ir)
    gpt1 = GPT1File.from_bytes(blob)
    assert gpt1.ptl.generators[0].gen_type == 7
    assert gpt1.ptl.generators[0].flags == 0xABCD
    assert gpt1.ptl.generators[0].params[:3] == pytest.approx(params[:3])


def test_real_models_full_round_trip():
    """Every priority model with GPT1 must round-trip: describe → compose → re-describe."""
    import os
    from shared.helpers.pkx import PKXContainer
    from importer.phases.describe.helpers.particles import describe_particles as ir_describe

    models_dir = '/Users/stars/Documents/Projects/DAT plugin/models'
    if not os.path.isdir(models_dir):
        pytest.skip('Real models not available')
    for name in ['ghos', 'lizardon', 'fire', 'freezer', 'showers']:
        path = os.path.join(models_dir, f'{name}.pkx')
        if not os.path.exists(path):
            continue
        container = PKXContainer.from_file(path)
        if not container.gpt1_data:
            continue
        ir1 = ir_describe(container.gpt1_data)
        assert ir1 is not None, name

        # Compose to bytes, then re-describe.
        blob = compose_particles(ir1)
        assert blob, name
        ir2 = ir_describe(blob)
        assert ir2 is not None, name
        assert len(ir2.generators) == len(ir1.generators), name

        for i, (g1, g2) in enumerate(zip(ir1.generators, ir2.generators)):
            assert g1.gen_type == g2.gen_type, f'{name} gen {i}'
            assert g1.lifetime == g2.lifetime, f'{name} gen {i}'
            assert g1.max_particles == g2.max_particles, f'{name} gen {i}'
            assert g1.flags == g2.flags, f'{name} gen {i}'
            assert len(g1.instructions) == len(g2.instructions), f'{name} gen {i}'
            for j, (a, b) in enumerate(zip(g1.instructions, g2.instructions)):
                assert a.mnemonic == b.mnemonic, f'{name} gen {i} ins {j}'
                assert a.args == b.args, f'{name} gen {i} ins {j}'


def test_ir_to_gpt1_to_ir_preserves_instruction_semantics():
    """Full round-trip: IR → GPT1 bytes → re-parse → IR-shaped instructions match."""
    from importer.phases.describe.helpers.particles import describe_particles as ir_describe

    original_instructions = [
        _ins('LIFETIME', frames=20),
        _ins('SET_PRIMCOL', time=0, r=100, g=200, b=50, a=255),
        _ins('LIFETIME', frames=40),
        _ins('SCALE', time=10, target=2.0),
        _ins('LOOP_START', count=3),
        _ins('LIFETIME', frames=5),
        _ins('LOOP_END'),
        _ins('EXIT'),
    ]
    ir = IRParticleSystem(generators=[_generator(original_instructions, max_particles=4)])
    blob = compose_particles(ir)

    ir2 = ir_describe(blob)
    assert ir2 is not None
    assert len(ir2.generators) == 1

    recovered = ir2.generators[0].instructions
    assert len(recovered) == len(original_instructions)
    for orig, got in zip(original_instructions, recovered):
        assert got.mnemonic == orig.mnemonic
        assert got.args == orig.args
