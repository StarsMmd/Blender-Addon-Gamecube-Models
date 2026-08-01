"""Tests for GPT1 bytecode → semantic IRParticleSystem summarization."""
import pytest

from importer.phases.describe.helpers.particles import describe_particles
from shared.helpers.gpt1 import (
    GPT1File, PTLSection, TXGSection, GeneratorDef, TextureContainer,
)
from shared.helpers.gpt1_commands import ParticleInstruction, assemble
from shared.helpers.scale import GC_TO_METERS


def _ins(mnemonic, **args):
    return ParticleInstruction(offset=0, opcode=0, mnemonic=mnemonic, args=args)


def _gpt1_bytes(instruction_lists, ref_ids=None, n_textures=0,
                lifetime=120, max_particles=12, params=None, gen_type=0,
                flags=0):
    """Build a GPT1 blob from per-generator instruction lists."""
    generators = [
        GeneratorDef(
            gen_type=gen_type, unknown_02=0, lifetime=lifetime,
            max_particles=max_particles, flags=flags,
            params=params or (0.0,) * 12,
            command_bytes=assemble(ins_list),
        )
        for ins_list in instruction_lists
    ]
    containers = [
        TextureContainer(nb_textures=1, format=0x5, data_offset=0,
                         width=0, height=0, nb_mipmaps=0, texture_offsets=[0])
        for _ in range(n_textures)
    ]
    gpt1 = GPT1File(
        ptl=PTLSection(version=0x43, unknown_02=0, skip_sections=0,
                       generators=generators),
        txg=TXGSection(containers=containers),
        tex_data=b'',
        ref_ids=ref_ids if ref_ids is not None else list(range(len(generators))),
    )
    return gpt1.to_bytes()


def _describe_one(instructions, **kwargs):
    system = describe_particles(_gpt1_bytes([instructions], **kwargs))
    assert system is not None
    return system.emitters[0]


# ---------------------------------------------------------------------------
# Birth phase
# ---------------------------------------------------------------------------

def test_birth_initializers_map_to_birth_state():
    e = _describe_one([
        _ins('SET_POS', x=10.0, y=20.0),
        _ins('SET_VEL', y=1.0),
        _ins('RAND_OFFSET', x=2.0, y=0.0, z=4.0),
        _ins('RAND_ROTATE', base=1.0, range=2.0, param=0),
        _ins('LIFETIME', frames=30),
        _ins('EXIT'),
    ])
    assert e.birth.position.base == pytest.approx((1.0, 2.0, 0.0))
    assert e.birth.velocity.base == pytest.approx((0.0, 0.1, 0.0))
    assert e.birth.position.spread == pytest.approx((0.2, 0.0, 0.4))
    # uniform [base, base+range] → base+range/2 ± range/2
    assert e.rotation.initial.base == pytest.approx(2.0)
    assert e.rotation.initial.spread == pytest.approx(1.0)
    assert e.particle_lifetime.base == 30


def test_zero_frame_lifetime_keeps_birth_phase():
    e = _describe_one([
        _ins('LIFETIME_TEX', frames=0, texture=0),
        _ins('SCALE_RAND', time=0, base=1.0, range=2.0),
        _ins('LIFETIME', frames=10),
        _ins('EXIT'),
    ], n_textures=1)
    # SCALE_RAND after a zero-frame frame-select is still a birth initializer.
    # It draws uniformly over [base, base+range] — 1..3 source units, which is
    # 0.1..0.3 metres once scaled into IR units.
    assert e.birth.size.base == pytest.approx(2.0 * GC_TO_METERS)
    assert e.birth.size.spread == pytest.approx(1.0 * GC_TO_METERS)
    assert e.size_over_life == []


def test_post_birth_position_ops_are_dropped():
    e = _describe_one([
        _ins('LIFETIME', frames=10),
        _ins('SET_POS', x=5.0),
        _ins('EXIT'),
    ])
    assert e.birth.position.base == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Over-life curves
# ---------------------------------------------------------------------------

def test_color_gradient_with_hold_keys():
    e = _describe_one([
        _ins('SET_PRIMCOL', time=10, r=255, g=0, b=0, a=255),
        _ins('LIFETIME', frames=20),
        _ins('SET_PRIMCOL', time=5, r=0, g=0, b=255, a=255),
        _ins('LIFETIME', frames=10),
        _ins('EXIT'),
    ])
    assert e.particle_lifetime.base == 30
    ages = [round(s.age, 4) for s in e.color_over_life]
    # white anchor, ramp to red by 10, hold red to 20, ramp to blue by 25
    assert ages == [0.0, round(10 / 30, 4), round(20 / 30, 4), round(25 / 30, 4)]
    assert e.color_over_life[0].rgba == (1.0, 1.0, 1.0, 1.0)
    assert e.color_over_life[1].rgba == (1.0, 0.0, 0.0, 1.0)
    assert e.color_over_life[2].rgba == (1.0, 0.0, 0.0, 1.0)
    assert e.color_over_life[3].rgba == (0.0, 0.0, 1.0, 1.0)


def test_new_op_snaps_pending_ramp():
    e = _describe_one([
        _ins('SET_PRIMCOL', time=100, r=255, g=0, b=0, a=255),
        _ins('SET_PRIMCOL', time=5, r=0, g=255, b=0, a=255),
        _ins('LIFETIME', frames=10),
        _ins('EXIT'),
    ])
    # The 100-frame ramp is snapped complete when the second op fires at 0.
    ages = [round(s.age, 4) for s in e.color_over_life]
    assert ages == [0.0, 0.5]
    assert e.color_over_life[0].rgba == (1.0, 0.0, 0.0, 1.0)
    assert e.color_over_life[1].rgba == (0.0, 1.0, 0.0, 1.0)


def test_size_curve_keys():
    # params[8] seeds the pre-bytecode scale the first curve key anchors to.
    e = _describe_one([
        _ins('LIFETIME', frames=50),
        _ins('SCALE', time=50, target=3.0),
        _ins('LIFETIME', frames=50),
        _ins('EXIT'),
    ], params=(0.0,) * 8 + (1.0,) + (0.0,) * 3)
    # Sizes are metres in the IR: 1 and 3 source units become 0.1 and 0.3.
    keys = [(round(k.age, 2), round(k.value, 4)) for k in e.size_over_life]
    assert keys == [(0.0, round(1.0 * GC_TO_METERS, 4)),
                    (0.5, round(1.0 * GC_TO_METERS, 4)),
                    (1.0, round(3.0 * GC_TO_METERS, 4))]


def test_channel_subset_color_op_keeps_other_channels():
    e = _describe_one([
        _ins('SET_PRIMCOL', time=0, r=0, g=0, b=0, a=255),
        _ins('LIFETIME', frames=10),
        _ins('SET_PRIMCOL', time=0, a=0),   # alpha-only fade
        _ins('EXIT'),
    ])
    assert e.color_over_life[-1].rgba == (0.0, 0.0, 0.0, 0.0)


def test_env_color_composited_only_with_primenv():
    ops = [
        _ins('SET_PRIMCOL', time=0, r=128, g=0, b=0, a=255),
        _ins('SET_ENVCOL', time=0, r=0, g=128, b=0, a=0),
        _ins('LIFETIME', frames=10),
        _ins('EXIT'),
    ]
    plain = _describe_one(ops)
    assert plain.color_over_life[-1].rgba == pytest.approx((128 / 255, 0.0, 0.0, 1.0))

    composited = _describe_one([_ins('PRIMENV_ON')] + ops)
    assert composited.color_over_life[-1].rgba == pytest.approx(
        (128 / 255, 128 / 255, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Lifetime, loops, kill timers
# ---------------------------------------------------------------------------

def test_bounded_loop_unrolls_into_lifetime():
    e = _describe_one([
        _ins('LOOP_START', count=3),
        _ins('LIFETIME', frames=10),
        _ins('LOOP_END'),
        _ins('EXIT'),
    ])
    assert e.particle_lifetime.base == 30
    assert e.looping is False


def test_jump_marks_looping():
    e = _describe_one([
        _ins('SAVE_JUMP'),
        _ins('LIFETIME', frames=8),
        _ins('JUMP'),
    ])
    assert e.looping is True
    assert e.particle_lifetime.base == 8


def test_rand_kill_timer_sets_lifetime_spread():
    e = _describe_one([
        _ins('RAND_KILL_TIMER', base=80, range=40),
        _ins('LIFETIME', frames=200),
        _ins('EXIT'),
    ])
    assert e.particle_lifetime.base == 200
    assert e.particle_lifetime.spread == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# Flip-book, render state, forces
# ---------------------------------------------------------------------------

def test_flipbook_frames_and_ages():
    e = _describe_one([
        _ins('LIFETIME_TEX', frames=10, texture=0),
        _ins('LIFETIME_TEX', frames=10, texture=1),
        _ins('EXIT'),
    ], n_textures=2)
    assert e.texture.frames == (0, 1)
    assert e.texture.frame_ages == pytest.approx((0.0, 0.5))


def test_out_of_range_flipbook_indices_dropped():
    e = _describe_one([
        _ins('LIFETIME_TEX', frames=10, texture=0),
        _ins('LIFETIME_TEX', frames=10, texture=99),
        _ins('EXIT'),
    ], n_textures=1)
    assert e.texture.frames == (0,)


def test_zero_duration_flip_keeps_last():
    e = _describe_one([
        _ins('LIFETIME_TEX', frames=0, texture=0),
        _ins('LIFETIME_TEX', frames=10, texture=1),
        _ins('EXIT'),
    ], n_textures=2)
    assert e.texture.frames == (1,)


def test_render_state_scan():
    e = _describe_one([
        _ins('TEX_OFF'),
        _ins('DIRVEC_ON'),
        _ins('NO_ZCOMP'),
        _ins('TEXINTERP_NEAR'),
        _ins('MIRROR_ST'),
        _ins('SET_TRAIL', length=5.0),
        _ins('LIFETIME', frames=10),
        _ins('EXIT'),
    ])
    assert e.render.textured is False
    assert e.render.billboard == 'VELOCITY_STRETCH'
    assert e.render.depth_test is False
    assert e.render.trail_length == pytest.approx(5.0 * GC_TO_METERS)
    assert e.texture.filter == 'NEAREST'
    assert e.texture.wrap_s == 'MIRROR'
    assert e.texture.wrap_t == 'MIRROR'


def test_gravity_and_friction():
    e = _describe_one([
        _ins('GRAVITY', value=-2.0),
        _ins('FRICTION', value=0.9),
        _ins('LIFETIME', frames=10),
        _ins('EXIT'),
    ])
    # The integrator subtracts the stored gravity from vel.y, so a negative
    # stored value is upward acceleration.
    assert e.forces.gravity == pytest.approx((0.0, 0.2, 0.0))
    assert e.forces.drag == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# Sub-emitters
# ---------------------------------------------------------------------------

def test_sub_emitter_resolved_via_ref_table():
    blob = _gpt1_bytes([
        [
            _ins('LIFETIME', frames=10),
            _ins('SPAWN_GENERATOR', id=101),
            _ins('LIFETIME', frames=10),
            _ins('EXIT'),
        ],
        [_ins('EXIT')],
    ], ref_ids=[100, 101])
    system = describe_particles(blob)
    subs = system.emitters[0].sub_emitters
    assert len(subs) == 1
    assert subs[0].emitter_ref == 1
    assert subs[0].age == pytest.approx(0.5)
    assert subs[0].inherit_velocity is False


def test_sub_emitter_velocity_variant():
    blob = _gpt1_bytes([
        [
            _ins('SPAWN_PARTICLE_VEL', id=1),
            _ins('LIFETIME', frames=10),
            _ins('EXIT'),
        ],
        [_ins('EXIT')],
    ])
    subs = describe_particles(blob).emitters[0].sub_emitters
    assert subs[0].inherit_velocity is True
    assert subs[0].emitter_ref == 1


def test_unresolvable_spawn_target_dropped():
    e = _describe_one([
        _ins('SPAWN_GENERATOR', id=999),
        _ins('LIFETIME', frames=10),
        _ins('EXIT'),
    ])
    assert e.sub_emitters == []


# ---------------------------------------------------------------------------
# Header / emission / params
# ---------------------------------------------------------------------------

def test_emission_rate_from_header():
    # params[7] drives the spawn accumulator: positive means p7 x rand per
    # frame (mean p7/2, jittered); negative means exactly |p7| per frame.
    params = (0.0,) * 7 + (3.0,) + (0.0,) * 4
    e = _describe_one([_ins('LIFETIME', frames=10), _ins('EXIT')],
                      lifetime=60, max_particles=30, params=params)
    assert e.emit_duration == 60
    assert e.max_particles == 30
    assert e.emission.rate == pytest.approx(1.5)
    assert e.emission.rate_jitter is True


def test_emission_rate_negative_is_exact():
    params = (0.0,) * 7 + (-2.0,) + (0.0,) * 4
    e = _describe_one([_ins('LIFETIME', frames=10), _ins('EXIT')], params=params)
    assert e.emission.rate == pytest.approx(2.0)
    assert e.emission.rate_jitter is False


def test_header_gravity_and_friction_defaults():
    # params[0] seeds per-particle gravity, params[1] the friction factor;
    # each is live only when its enable flag bit is set, and the integrator
    # subtracts gravity from vel.y (negative stored = upward).
    params = (-2.0, 0.95) + (0.0,) * 10
    e = _describe_one([_ins('LIFETIME', frames=10), _ins('EXIT')],
                      params=params, flags=0x3)
    assert e.forces.gravity == pytest.approx((0.0, 0.2, 0.0))
    assert e.forces.drag == pytest.approx(0.05)


def test_header_forces_ignored_without_enable_flags():
    params = (-2.0, 0.95) + (0.0,) * 10
    e = _describe_one([_ins('LIFETIME', frames=10), _ins('EXIT')],
                      params=params, flags=0x0)
    assert e.forces.gravity == (0.0, 0.0, 0.0)
    assert e.forces.drag == 0.0


def test_bytecode_gravity_overrides_header():
    params = (-2.0,) + (0.0,) * 11
    e = _describe_one([_ins('GRAVITY', value=-5.0),
                       _ins('LIFETIME', frames=10), _ins('EXIT')],
                      params=params, flags=0x1)
    assert e.forces.gravity == pytest.approx((0.0, 0.5, 0.0))


def test_disc_shape_from_header():
    # gen_type 0 with radius, cone angle, and an explicit arc.
    params = (0, 0, 0.0, 2.0, 0.0, 3.0, 0.35, 0, 0, 0.5, 1.5, 0)
    e = _describe_one([_ins('LIFETIME', frames=10), _ins('EXIT')],
                      params=params, gen_type=0)
    s = e.emission.shape
    assert s.kind == 'DISC'
    assert s.radius == pytest.approx(0.3)
    assert not s.ring and not s.uniform_area and not s.sweep
    assert s.cone_angle == pytest.approx(0.35)
    assert (s.arc_start, s.arc_end) == (0.5, 1.5)
    assert s.velocity == pytest.approx((0.0, 0.2, 0.0))


def test_disc_ring_sweep_and_uniform_area():
    params = (0, 0, 0, 0, 0, -3.0, -0.35, 0, 0, 0, 0, 0)
    e = _describe_one([_ins('LIFETIME', frames=10), _ins('EXIT')],
                      params=params, gen_type=3)
    s = e.emission.shape
    assert s.kind == 'DISC' and s.uniform_area
    assert s.ring and s.radius == pytest.approx(0.3)
    assert s.sweep and s.cone_angle == pytest.approx(0.35)
    # both-zero arc = full circle, kept verbatim
    assert (s.arc_start, s.arc_end) == (0.0, 0.0)


def test_box_shape_from_header():
    params = (0, 0, 0, 0, 0, 0, 0, 0, 0, 25.0, -10.0, 0.1)
    e = _describe_one([_ins('LIFETIME', frames=10), _ins('EXIT')],
                      params=params, gen_type=5)
    s = e.emission.shape
    assert s.kind == 'BOX'
    assert s.box_extents == pytest.approx((2.5, -1.0, 0.01))


def test_sphere_shape_from_header():
    params = (0, 0, 0, 0, 0, -3.0, 0, 0, 0, 3.0, 3.0, 1.2)
    e = _describe_one([_ins('LIFETIME', frames=10), _ins('EXIT')],
                      params=params, gen_type=8)
    s = e.emission.shape
    assert s.kind == 'SPHERE'
    assert s.ring and s.radius == pytest.approx(0.3)
    assert s.radial_speed == pytest.approx(0.3)
    assert s.polar_max == pytest.approx(1.2)


def test_initial_scale_from_header():
    params = (0.0,) * 8 + (2.0,) + (0.0,) * 3
    e = _describe_one([_ins('LIFETIME', frames=10), _ins('EXIT')], params=params)
    assert e.birth.size.base == pytest.approx(0.2)


def test_dropped_opcodes_do_not_crash():
    e = _describe_one([
        _ins('MODIFY_DIR', value=1.0),
        _ins('SET_CALLBACK', id=3),
        _ins('CUSTOM_FLOAT', index=0, value=2.0),
        _ins('LIFETIME', frames=10),
        _ins('EXIT'),
    ])
    assert e.particle_lifetime.base == 10


def test_empty_and_invalid_data():
    assert describe_particles(b'') is None
    assert describe_particles(b'NOPE' + b'\x00' * 64) is None
