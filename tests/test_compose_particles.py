"""Tests for semantic IRParticleSystem → GPT1 bytes synthesis."""
import pytest

from exporter.phases.compose.helpers.particles import compose_particles
from importer.phases.describe.helpers.particles import describe_particles, _sample_stops
from shared.IR.particles import (
    IRParticleSystem, IRParticleEmitter, IRParticleTexture,
    IRRandomScalar, IRRandomVec3, IRColorStop, IRScalarKey,
    IRParticleEmission, IRParticleBirth, IRParticleRotation, IRParticleForces,
    IRParticleTextureAnim, IRParticleRender, IRSubEmitter,
)
from shared.helpers.gpt1 import GPT1File
from shared.helpers.gpt1_commands import disassemble


def _emitter(**overrides):
    defaults = dict(
        name="G00",
        emit_duration=120.0,
        max_particles=12,
        particle_lifetime=IRRandomScalar(base=100.0),
    )
    defaults.update(overrides)
    return IRParticleEmitter(**defaults)


def _mnemonics(blob, gen_index=0):
    gpt1 = GPT1File.from_bytes(blob)
    return [i.mnemonic for i in
            disassemble(gpt1.ptl.generators[gen_index].command_bytes)]


def test_empty_particle_system_emits_empty_bytes():
    assert compose_particles(IRParticleSystem()) == b''
    assert compose_particles(None) == b''


def test_header_defaults_and_identity_refs():
    ir = IRParticleSystem(emitters=[
        _emitter(emit_duration=60.0, max_particles=8),
        _emitter(),
    ])
    gpt1 = GPT1File.from_bytes(compose_particles(ir))
    assert len(gpt1.ptl.generators) == 2
    assert gpt1.ptl.generators[0].lifetime == 60
    assert gpt1.ptl.generators[0].max_particles == 8
    assert gpt1.ref_ids == [0, 1]


def test_birth_and_render_ops_emitted():
    ir = IRParticleSystem(emitters=[_emitter(
        particle_lifetime=IRRandomScalar(base=100.0, spread=10.0),
        birth=IRParticleBirth(
            position=IRRandomVec3(base=(1.0, 0.0, 0.0), spread=(0.5, 0.5, 0.5)),
            velocity=IRRandomVec3(base=(0.0, 0.2, 0.0)),
            size=IRRandomScalar(base=2.0),
        ),
        rotation=IRParticleRotation(
            initial=IRRandomScalar(base=1.0, spread=1.0),
            rate=IRRandomScalar(base=0.1)),
        forces=IRParticleForces(gravity=(0.0, -0.1, 0.0), drag=0.05),
        render=IRParticleRender(textured=False, billboard='VELOCITY_STRETCH',
                                depth_test=False, trail_length=0.5),
        texture=IRParticleTextureAnim(filter='NEAREST', wrap_s='MIRROR',
                                      wrap_t='MIRROR'),
    )])
    mnemonics = _mnemonics(compose_particles(ir))
    for expected in ('TEX_OFF', 'DIRVEC_ON', 'NO_ZCOMP', 'SET_TRAIL',
                     'TEXINTERP_NEAR', 'MIRROR_ST', 'RAND_KILL_TIMER',
                     'SET_POS', 'RAND_OFFSET', 'SET_VEL', 'SCALE',
                     'RAND_ROTATE', 'ROTATE_RAND', 'GRAVITY', 'FRICTION'):
        assert expected in mnemonics, expected
    assert mnemonics[-1] == 'EXIT'


def test_looping_wraps_save_jump():
    ir = IRParticleSystem(emitters=[_emitter(
        particle_lifetime=IRRandomScalar(base=20.0), looping=True)])
    mnemonics = _mnemonics(compose_particles(ir))
    assert 'SAVE_JUMP' in mnemonics
    assert mnemonics[-1] == 'JUMP'
    assert 'EXIT' not in mnemonics


def test_long_lifetime_gap_split():
    ir = IRParticleSystem(emitters=[_emitter(
        particle_lifetime=IRRandomScalar(base=20000.0),
        color_over_life=[
            IRColorStop(age=0.0, rgba=(1.0, 0.0, 0.0, 1.0)),
            IRColorStop(age=1.0, rgba=(1.0, 0.0, 0.0, 0.0)),
        ],
    )])
    gpt1 = GPT1File.from_bytes(compose_particles(ir))
    instructions = disassemble(gpt1.ptl.generators[0].command_bytes)
    waits = [i.args['frames'] for i in instructions if i.mnemonic == 'LIFETIME']
    assert all(w <= 0x1FFF for w in waits)
    assert sum(waits) == 20000


def test_texture_container_encoding():
    pixels = bytes(range(0, 256)) * (8 * 8 * 4 // 256)
    ir = IRParticleSystem(
        emitters=[_emitter()],
        textures=[IRParticleTexture(width=8, height=8, pixels=pixels)],
    )
    blob = compose_particles(ir)
    gpt1 = GPT1File.from_bytes(blob)
    assert len(gpt1.txg.containers) == 1
    assert gpt1.txg.containers[0].width == 8
    assert gpt1.txg.containers[0].height == 8
    # Re-describe decodes the texture back to full-size RGBA.
    system = describe_particles(blob)
    assert len(system.textures) == 1
    assert len(system.textures[0].pixels) == 8 * 8 * 4


def test_semantic_roundtrip_full_feature_emitter():
    """IR → GPT1 bytes → IR reproduces every kept field within tolerance."""
    original = IRParticleSystem(emitters=[
        _emitter(
            particle_lifetime=IRRandomScalar(base=100.0, spread=20.0),
            birth=IRParticleBirth(
                position=IRRandomVec3(base=(0.5, 0.0, 0.0), spread=(0.1, 0.2, 0.3)),
                velocity=IRRandomVec3(base=(0.0, 0.1, 0.0), spread=(0.2, 0.0, 0.0)),
                size=IRRandomScalar(base=1.5, spread=0.5),
            ),
            color_over_life=[
                IRColorStop(age=0.0, rgba=(1.0, 1.0, 1.0, 0.0)),
                IRColorStop(age=0.3, rgba=(1.0, 0.4, 0.0, 1.0)),
                IRColorStop(age=1.0, rgba=(0.6, 0.0, 0.0, 0.0)),
            ],
            # The age-0 key anchors at the birth size (describe invariant).
            size_over_life=[
                IRScalarKey(age=0.0, value=1.5),
                IRScalarKey(age=0.5, value=2.0),
                IRScalarKey(age=1.0, value=0.5),
            ],
            rotation=IRParticleRotation(
                initial=IRRandomScalar(base=1.5707, spread=1.5707),
                rate=IRRandomScalar(base=0.05)),
            forces=IRParticleForces(gravity=(0.0, -0.15, 0.0), drag=0.25),
            texture=IRParticleTextureAnim(
                frames=(0, 1, 0), frame_ages=(0.0, 0.25, 0.6)),
            sub_emitters=[IRSubEmitter(age=0.5, emitter_ref=1)],
        ),
        _emitter(name="G01", particle_lifetime=IRRandomScalar(base=30.0)),
    ], textures=[
        IRParticleTexture(width=4, height=4, pixels=b'\xff' * 64),
        IRParticleTexture(width=4, height=4, pixels=b'\x80' * 64),
    ])

    recovered = describe_particles(compose_particles(original))
    assert recovered is not None
    assert len(recovered.emitters) == 2
    e1, e2 = original.emitters[0], recovered.emitters[0]

    assert e2.particle_lifetime.base == pytest.approx(e1.particle_lifetime.base)
    assert e2.particle_lifetime.spread == pytest.approx(e1.particle_lifetime.spread)
    assert e2.emit_duration == pytest.approx(e1.emit_duration)
    assert e2.max_particles == e1.max_particles

    # Gradients compared by dense sampling (stop layout may differ).
    for t in range(0, 21):
        age = t / 20
        c1 = _sample_stops(e1.color_over_life, age)
        c2 = _sample_stops(e2.color_over_life, age)
        assert c1 == pytest.approx(c2, abs=0.02), age

    keys1 = [(round(k.age, 2), round(k.value, 3)) for k in e1.size_over_life]
    keys2 = [(round(k.age, 2), round(k.value, 3)) for k in e2.size_over_life]
    assert keys1 == keys2

    assert e2.birth.position.base == pytest.approx(e1.birth.position.base, abs=1e-6)
    assert e2.birth.position.spread == pytest.approx(e1.birth.position.spread, abs=1e-6)
    assert e2.birth.velocity.base == pytest.approx(e1.birth.velocity.base, abs=1e-6)
    assert e2.birth.velocity.spread == pytest.approx(e1.birth.velocity.spread, abs=1e-6)
    assert e2.birth.size.base == pytest.approx(e1.birth.size.base)
    assert e2.birth.size.spread == pytest.approx(e1.birth.size.spread)

    assert e2.rotation.initial.base == pytest.approx(e1.rotation.initial.base, abs=1e-4)
    assert e2.rotation.initial.spread == pytest.approx(e1.rotation.initial.spread, abs=1e-4)
    assert e2.rotation.rate.base == pytest.approx(e1.rotation.rate.base, abs=1e-6)

    assert e2.forces.gravity == pytest.approx(e1.forces.gravity, abs=1e-6)
    assert e2.forces.drag == pytest.approx(e1.forces.drag, abs=1e-6)

    assert e2.texture.frames == e1.texture.frames
    assert e2.texture.frame_ages == pytest.approx(e1.texture.frame_ages, abs=0.01)

    assert len(e2.sub_emitters) == 1
    assert e2.sub_emitters[0].emitter_ref == 1
    assert e2.sub_emitters[0].age == pytest.approx(0.5, abs=0.01)


def test_real_models_semantic_round_trip():
    """Every GPT1-bearing model must survive describe → compose → re-describe."""
    import os
    from shared.helpers.pkx import PKXContainer

    models_dir = '/Users/stars/Documents/Projects/DAT plugin/models'
    if not os.path.isdir(models_dir):
        pytest.skip('Real models not available')
    tested = 0
    for name in ['ghos', 'lizardon', 'fire', 'freezer', 'showers']:
        path = os.path.join(models_dir, f'{name}.pkx')
        if not os.path.exists(path):
            continue
        container = PKXContainer.from_file(path)
        if not container.gpt1_data:
            continue
        ir1 = describe_particles(container.gpt1_data)
        assert ir1 is not None, name

        blob = compose_particles(ir1)
        assert blob, name
        ir2 = describe_particles(blob)
        assert ir2 is not None, name
        assert len(ir2.emitters) == len(ir1.emitters), name
        assert len(ir2.textures) == len(ir1.textures), name

        for i, (e1, e2) in enumerate(zip(ir1.emitters, ir2.emitters)):
            ctx = f'{name} emitter {i}'
            assert e2.particle_lifetime.base == pytest.approx(
                e1.particle_lifetime.base, abs=1.5), ctx
            assert e2.looping == e1.looping, ctx
            assert e2.max_particles == e1.max_particles, ctx
            assert e2.texture.frames == e1.texture.frames, ctx
            if e1.color_over_life:
                for t in range(0, 11):
                    age = t / 10
                    c1 = _sample_stops(e1.color_over_life, age)
                    c2 = _sample_stops(e2.color_over_life, age)
                    assert c1 == pytest.approx(c2, abs=0.03), f'{ctx} color@{age}'
        tested += 1
    assert tested > 0
