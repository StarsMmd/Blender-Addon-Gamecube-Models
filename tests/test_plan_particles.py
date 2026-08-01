"""Unit tests for the Plan phase's IR particles → BR particles helper.

Covers the decisions the plan leg owns: node-group interface layout,
Y-up→Z-up flips, sRGB→linear ramp stops, ramp/curve
position layout (coincident ages, the 32-element ceiling, saturation), the
emitter material graph, and the flat custom-prop arrays.
"""
from types import SimpleNamespace

import pytest

from shared.IR.particles import (
    IRRandomScalar, IRRandomVec3, IRColorStop, IRScalarKey,
    IRParticleEmission, IRParticleBirth, IRParticleRotation, IRParticleForces,
    IRParticleTextureAnim, IRParticleRender, IRSubEmitter, IRParticleEmitter,
    IRParticleTexture, IRParticleSystem, IRParticleEmitEvent,
)
from shared.BR.materials import BRImage, BRMaterial
from shared.BR.particles import BRParticleSystem, BRParticleEmitter
from shared.helpers.srgb import srgb_to_linear
from importer.phases.plan.helpers.particles import (
    plan_particles, _lay_out, _downsample, _extension_for,
)


def _emitter(**overrides):
    """IRParticleEmitter with everything defaulted, overridable per test."""
    defaults = dict(
        name='G00',
        emit_duration=60.0,
        max_particles=32,
        particle_lifetime=IRRandomScalar(base=30.0, spread=4.0),
        looping=False,
        emission=IRParticleEmission(rate=2.0),
        birth=IRParticleBirth(),
        color_over_life=[],
        size_over_life=[],
        rotation=IRParticleRotation(),
        forces=IRParticleForces(),
        texture=IRParticleTextureAnim(),
        render=IRParticleRender(),
        sub_emitters=[],
    )
    defaults.update(overrides)
    return IRParticleEmitter(**defaults)


def _system(emitters=None, textures=None):
    return IRParticleSystem(
        emitters=emitters if emitters is not None else [_emitter()],
        textures=textures or [],
    )


def _plan(system=None, model='pika'):
    return plan_particles(system if system is not None else _system(), model)


def _inputs(br_emitter):
    """Interface inputs keyed by socket name."""
    return {s.name: s for s in br_emitter.node_group.inputs}


def _node_types(br_material):
    return {n.node_type for n in br_material.node_graph.nodes}


class TestSystem:

    def test_none_returns_none(self):
        assert plan_particles(None, 'pika') is None

    def test_empty_emitters_returns_none(self):
        assert plan_particles(IRParticleSystem(), 'pika') is None

    def test_root_and_object_names(self):
        br = _plan()
        assert isinstance(br, BRParticleSystem)
        assert br.root_name == 'Particles_pika'
        assert br.emitters[0].name == 'Particles_pika_G00'

    def test_group_and_material_names(self):
        emitter = _plan().emitters[0]
        assert emitter.node_group.name == 'DATPlugin_Particles_pika_G00'
        assert emitter.material.name == 'DATPlugin_ParticleMat_pika_G00'

    def test_unnamed_emitter_falls_back_to_slot_suffix(self):
        br = _plan(_system(emitters=[_emitter(name=''), _emitter(name='')]))
        assert [e.name for e in br.emitters] == ['Particles_pika_G00',
                                                 'Particles_pika_G01']

    def test_one_image_per_texture(self):
        br = _plan(_system(textures=[
            IRParticleTexture(width=8, height=8, pixels=b'\xff' * 256),
            IRParticleTexture(width=4, height=4, pixels=b'\x00' * 64),
        ]))
        assert [i.name for i in br.images] == ['DATPlugin_ParticleTex_pika_T00',
                                               'DATPlugin_ParticleTex_pika_T01']
        assert all(isinstance(i, BRImage) for i in br.images)
        assert br.images[0].pixels == b'\xff' * 256
        assert len({i.cache_key for i in br.images}) == 2

    def test_emitters_planned_in_order(self):
        br = _plan(_system(emitters=[_emitter(name='G00'), _emitter(name='G01')]))
        assert len(br.emitters) == 2
        assert all(isinstance(e, BRParticleEmitter) for e in br.emitters)


class TestInterfaceInputs:

    def test_geometry_socket_leads(self):
        group = _plan().emitters[0].node_group
        assert group.inputs[0].name == 'Geometry'
        assert group.inputs[0].socket_type == 'NodeSocketGeometry'
        assert [s.socket_type for s in group.outputs] == ['NodeSocketGeometry']

    def test_socket_names_unique(self):
        names = [s.name for s in _plan().emitters[0].node_group.inputs]
        assert len(names) == len(set(names))

    def test_scalars_carry_ir_values(self):
        sockets = _inputs(_plan().emitters[0])
        assert sockets['Emit Duration'].value == 60.0
        assert sockets['Max Particles'].value == 32
        assert sockets['Max Particles'].socket_type == 'NodeSocketInt'
        assert sockets['Emission Rate'].value == 2.0
        assert sockets['Lifetime'].value == 30.0
        assert sockets['Lifetime Spread'].value == 4.0

    def test_looping_is_boolean_socket(self):
        sockets = _inputs(_plan(_system([_emitter(looping=True)])).emitters[0])
        assert sockets['Looping'].socket_type == 'NodeSocketBool'
        assert sockets['Looping'].value is True

    def test_birth_vectors_stay_in_the_emitter_frame(self):
        # The emitter object inherits the armature's source→Blender rotation,
        # so the simulation runs in source axes (Y up) — converting here too
        # would rotate everything twice.
        birth = IRParticleBirth(
            position=IRRandomVec3(base=(1.0, 2.0, 3.0), spread=(0.5, 0.25, 0.125)),
            velocity=IRRandomVec3(base=(0.0, 4.0, 0.0)),
        )
        sockets = _inputs(_plan(_system([_emitter(birth=birth)])).emitters[0])
        assert sockets['Birth Position'].value == (1.0, 2.0, 3.0)
        assert sockets['Birth Position Spread'].value == (0.5, 0.25, 0.125)
        assert sockets['Birth Velocity'].value == (0.0, 4.0, 0.0)

    def test_gravity_stays_in_the_emitter_frame(self):
        forces = IRParticleForces(gravity=(0.0, 0.98, 0.0), drag=0.25)
        sockets = _inputs(_plan(_system([_emitter(forces=forces)])).emitters[0])
        assert sockets['Gravity'].value == (0.0, 0.98, 0.0)
        assert sockets['Drag'].value == 0.25
        assert sockets['Drag'].subtype == 'FACTOR'

    def test_sizes_carry_over_in_world_units(self):
        # IR lengths are already metres — describe scaled them — so plan must
        # not scale again or particles come out ten times too big.
        birth = IRParticleBirth(size=IRRandomScalar(base=0.2, spread=0.05))
        sockets = _inputs(_plan(_system([_emitter(birth=birth)])).emitters[0])
        assert sockets['Birth Size'].value == pytest.approx(0.2)
        assert sockets['Birth Size Spread'].value == pytest.approx(0.05)

    def test_rotation_channels(self):
        rotation = IRParticleRotation(
            initial=IRRandomScalar(base=0.5, spread=0.1),
            rate=IRRandomScalar(base=0.02, spread=0.01),
            accel=0.003,
        )
        sockets = _inputs(_plan(_system([_emitter(rotation=rotation)])).emitters[0])
        assert sockets['Rotation'].value == 0.5
        assert sockets['Rotation Spread'].value == 0.1
        assert sockets['Rotation Rate'].value == 0.02
        assert sockets['Rotation Rate Spread'].value == 0.01
        assert sockets['Rotation Accel'].value == 0.003
        assert sockets['Rotation'].subtype == 'ANGLE'

    def test_color_spread_is_rgba_socket(self):
        birth = IRParticleBirth(color_spread=(0.1, 0.2, 0.3, 0.4))
        sockets = _inputs(_plan(_system([_emitter(birth=birth)])).emitters[0])
        assert sockets['Color Spread'].socket_type == 'NodeSocketColor'
        assert sockets['Color Spread'].value == (0.1, 0.2, 0.3, 0.4)

    def test_render_enums_become_menu_ints(self):
        render = IRParticleRender(blend_mode='ADD', billboard='VELOCITY_STRETCH',
                                  textured=False, depth_test=False, trail_length=1.5)
        sockets = _inputs(_plan(_system([_emitter(render=render)])).emitters[0])
        assert sockets['Blend Mode'].value == 1
        assert sockets['Billboard'].value == 1
        assert sockets['Textured'].value is False
        assert sockets['Depth Test'].value is False
        assert sockets['Trail Length'].value == 1.5

    def test_unknown_enum_falls_back_to_zero(self):
        render = IRParticleRender(blend_mode='SUBTRACT')
        sockets = _inputs(_plan(_system([_emitter(render=render)])).emitters[0])
        assert sockets['Blend Mode'].value == 0


class TestNodeGroupContents:

    def test_ramp_and_curve_nodes_present(self):
        group = _plan().emitters[0].node_group
        names = {n.name: n.node_type for n in group.nodes}
        assert names['ColorOverLife'] == 'ShaderNodeValToRGB'
        assert names['SizeOverLife'] == 'ShaderNodeFloatCurve'
        assert names['Group Input'] == 'NodeGroupInput'
        assert names['Group Output'] == 'NodeGroupOutput'

    def test_payloads_keyed_by_node_name(self):
        group = _plan().emitters[0].node_group
        assert set(group.color_ramps) == {'ColorOverLife'}
        assert set(group.float_curves) == {'SizeOverLife'}

    def test_simulation_zone_declares_cadence_state(self):
        group = _plan().emitters[0].node_group
        names = {n.name: n.node_type for n in group.nodes}
        assert group.simulation_zones == [
            ('SimulationInput', 'SimulationOutput',
             [('FLOAT', 'Acc'), ('FLOAT', 'Age')])]
        assert names['SimulationInput'] == 'GeometryNodeSimulationInput'
        assert names['SimulationOutput'] == 'GeometryNodeSimulationOutput'

    def test_spawned_points_join_the_simulation_state(self):
        links = _plan().emitters[0].node_group.links
        into_join = {(l.from_node, l.to_input) for l in links
                     if l.to_node == 'AddSpawned'}
        assert ('SimulationInput', 'Geometry') in into_join
        assert ('StoreRollRate', 'Geometry') in into_join

    def test_particles_spawn_at_the_attach_object(self):
        links = _plan().emitters[0].node_group.links
        assert any(l.from_node == 'Group Input' and l.from_output == 'Attach'
                   and l.to_node == 'AttachInfo' for l in links)
        assert any(l.from_node == 'AttachInfo' and l.from_output == 'Location'
                   and l.to_node == 'SpawnPosWorld' for l in links)
        # Only the location — the source spawns in the world frame, so the
        # bone's orientation must not rotate positions or velocities.
        rotated = {l.to_node for l in links
                   if l.from_node == 'AttachInfo' and l.from_output == 'Rotation'}
        assert rotated == set()

    def test_age_drives_both_over_life_nodes(self):
        links = _plan().emitters[0].node_group.links
        driven = {l.to_node for l in links if l.from_node == 'NormalizedAge'}
        assert {'ColorOverLife', 'SizeOverLife'} <= driven

    def test_size_curve_scales_the_instances(self):
        links = _plan().emitters[0].node_group.links
        assert any(l.from_node == 'SizeOverLife' and l.to_node == 'Billboards'
                   and l.to_input == 'Scale' for l in links)

    def test_colour_ramp_is_stored_for_the_shader(self):
        group = _plan().emitters[0].node_group
        store = next(n for n in group.nodes if n.name == 'StoreColor')
        assert store.input_defaults['Name'] == 'particle_color'
        assert store.properties['data_type'] == 'FLOAT_COLOR'
        assert any(l.from_node == 'ColorOverLife' and l.to_node == 'StoreColor'
                   for l in group.links)

    def test_expired_particles_are_deleted(self):
        group = _plan().emitters[0].node_group
        retire = next(n for n in group.nodes if n.name == 'Retire')
        assert retire.node_type == 'GeometryNodeDeleteGeometry'
        assert retire.properties['domain'] == 'POINT'
        assert any(l.from_node == 'Expired' and l.to_node == 'Retire'
                   and l.to_input == 'Selection' for l in group.links)

    def test_lifetime_floored_before_dividing_by_it(self):
        group = _plan().emitters[0].node_group
        safe = next(n for n in group.nodes if n.name == 'LifeSafe')
        assert safe.properties['operation'] == 'MAXIMUM'
        assert safe.input_defaults['Value_001'] == 1.0
        # Per-particle lifetimes divide age for the over-life curves.
        assert any(l.from_node == 'RReadLife' and l.to_node == 'NormalizedAge'
                   for l in group.links)

    def test_group_output_comes_from_the_shaded_instances(self):
        links = _plan().emitters[0].node_group.links
        final = [l for l in links if l.to_node == 'Group Output']
        assert len(final) == 1
        assert final[0].from_node == 'ParticleMaterial'

    def test_every_link_names_a_real_node(self):
        group = _plan().emitters[0].node_group
        names = {n.name for n in group.nodes}
        for link in group.links:
            assert link.from_node in names, link
            assert link.to_node in names, link


class TestAttachPoints:
    """Which bone an emitter fires from is animation data; the attach Empty is
    the preview's way of showing it without pretending it is static."""

    def _system_with_clips(self, clips, emitters=2):
        """clips: [[(bone, emitter_index), ...], ...] — one list per clip."""
        anim_sets = []
        for i, events in enumerate(clips):
            tracks = {}
            for bone, emitter_index in events:
                track = tracks.setdefault(bone, SimpleNamespace(
                    bone_name=bone, particle_emits=[]))
                track.particle_emits.append(
                    IRParticleEmitEvent(frame=0.0, emitter_ref=emitter_index))
            anim_sets.append(SimpleNamespace(name='clip%d' % i,
                                             tracks=list(tracks.values())))
        system = _system([_emitter(name='G%02d' % i) for i in range(emitters)])
        return plan_particles(system, 'pika', anim_sets)

    def test_no_clips_means_no_attach_points(self):
        br = _plan()
        assert br.attaches == []
        assert br.emitters[0].attach_name is None

    def test_one_attach_per_firing_bone(self):
        br = self._system_with_clips([[('Head', 0), ('Tail', 1)]])
        assert [(a.name, a.bone_name) for a in br.attaches] == [
            ('Particles_pika_Attach_Head', 'Head'),
            ('Particles_pika_Attach_Tail', 'Tail'),
        ]

    def test_emitter_points_at_its_firing_bone(self):
        br = self._system_with_clips([[('Head', 0), ('Tail', 1)]])
        assert br.emitters[0].attach_name == 'Particles_pika_Attach_Head'
        assert br.emitters[1].attach_name == 'Particles_pika_Attach_Tail'

    def test_emitter_fired_from_several_bones_gets_one_instance_each(self):
        # The source spawns a generator instance per firing event, so an
        # emitter fired from two bones burns in both places at once.
        br = self._system_with_clips([[('Wing_L', 0), ('Wing_R', 0)]])
        instances = [e for e in br.emitters
                     if e.custom_props['dat_particle_emitter_index'] == 0]
        assert [e.attach_name for e in instances] == [
            'Particles_pika_Attach_Wing_L', 'Particles_pika_Attach_Wing_R']
        assert [e.name for e in instances] == [
            'Particles_pika_G00_Wing_L', 'Particles_pika_G00_Wing_R']
        assert [e.emit_driver.bone_name for e in instances] == ['Wing_L', 'Wing_R']
        # One template = one material; objects and groups stay unique.
        assert instances[0].material.name == instances[1].material.name
        assert instances[0].node_group.name != instances[1].node_group.name

    def test_attach_reaches_the_group_interface(self):
        br = self._system_with_clips([[('Head', 0)]])
        sockets = _inputs(br.emitters[0])
        assert sockets['Attach'].socket_type == 'NodeSocketObject'
        assert sockets['Attach'].value == 'Particles_pika_Attach_Head'

    def test_unfired_emitter_has_no_attach_value(self):
        br = self._system_with_clips([[('Head', 0)]])
        assert _inputs(br.emitters[1])['Attach'].value is None


class TestEmitGate:
    """The preview runs an emitter only while a clip fires it, so a scene
    shows what the game would rather than all emitters at once."""

    def _plan_with_clips(self, clips, emitters=2):
        anim_sets = []
        for i, events in enumerate(clips):
            tracks = {}
            for bone, emitter_index, frame in events:
                track = tracks.setdefault(bone, SimpleNamespace(
                    bone_name=bone, particle_emits=[]))
                track.particle_emits.append(
                    IRParticleEmitEvent(frame=frame, emitter_ref=emitter_index))
            anim_sets.append(SimpleNamespace(name='clip%d' % i,
                                             tracks=list(tracks.values())))
        system = _system([_emitter(name='G%02d' % i) for i in range(emitters)])
        return plan_particles(system, 'pika', anim_sets)

    def test_fired_emitter_gets_a_driver_on_its_bone(self):
        br = self._plan_with_clips([[('Head', 0, 0.0)]])
        driver = br.emitters[0].emit_driver
        assert driver.bone_name == 'Head'
        assert driver.emitter_index == 0
        assert driver.lane_count == 1

    def test_driver_covers_every_lane_the_bone_needs(self):
        # Two emitters fired from one bone on the same frame — two lanes.
        br = self._plan_with_clips([[('Head', 0, 0.0), ('Head', 1, 0.0)]])
        assert br.emitters[0].emit_driver.lane_count == 2
        assert br.emitters[1].emit_driver.lane_count == 2

    def test_unfired_emitter_has_no_driver(self):
        br = self._plan_with_clips([[('Head', 0, 0.0)]])
        assert br.emitters[1].emit_driver is None

    def test_fired_emitter_starts_gated_off(self):
        # The driver supplies the value; a non-zero default would leak a frame
        # of emission before it evaluates.
        br = self._plan_with_clips([[('Head', 0, 0.0)]])
        assert _inputs(br.emitters[0])['Emit'].value == 0.0

    def test_unfired_emitter_is_left_running(self):
        # Nothing will drive it, so gating it off would hide it forever.
        br = self._plan_with_clips([[('Head', 0, 0.0)]])
        assert _inputs(br.emitters[1])['Emit'].value == 1.0

    def test_emitters_without_animation_data_all_run(self):
        br = _plan()
        assert br.emitters[0].emit_driver is None
        assert _inputs(br.emitters[0])['Emit'].value == 1.0

    def test_gate_controls_the_accumulator(self):
        # The emit signal, the duration window, and the live cap multiply
        # into one gate that zeroes the accumulator while inactive.
        group = _plan().emitters[0].node_group
        links = group.links
        assert any(l.from_node == 'EmitOn' and l.to_node == 'Gate1' for l in links)
        assert any(l.from_node == 'LoopOrAge' and l.to_node == 'Gate1' for l in links)
        assert any(l.from_node == 'CountOK' and l.to_node == 'SpawnGate' for l in links)
        assert any(l.from_node == 'SpawnGate' and l.to_node == 'AccGated' for l in links)
        assert any(l.from_node == 'SpawnCountInt' and l.to_node == 'SpawnPoints'
                   and l.to_input == 'Count' for l in links)

    def test_accumulator_and_age_round_trip_the_zone_state(self):
        links = _plan().emitters[0].node_group.links
        assert any(l.from_node == 'AccNext' and l.to_node == 'SimulationOutput'
                   and l.to_input == 'Acc' for l in links)
        assert any(l.from_node == 'AgeNext' and l.to_node == 'SimulationOutput'
                   and l.to_input == 'Age' for l in links)
        assert any(l.from_node == 'SimulationInput' and l.from_output == 'Acc'
                   and l.to_node == 'AccPlus' for l in links)

    def test_live_count_enforces_the_cap(self):
        group = _plan().emitters[0].node_group
        count = next(n for n in group.nodes if n.name == 'LiveCount')
        assert count.node_type == 'GeometryNodeAttributeDomainSize'
        assert count.properties['component'] == 'POINTCLOUD'
        links = group.links
        assert any(l.from_node == 'LiveCount' and l.from_output == 'Point Count'
                   and l.to_node == 'CountOK' for l in links)
        assert any(l.from_node == 'Group Input' and l.from_output == 'Max Particles'
                   and l.to_node == 'CountOK' for l in links)

    def test_billboards_face_the_camera_with_roll(self):
        group = _plan().emitters[0].node_group
        links = group.links
        assert any(l.from_node == 'Group Input' and l.from_output == 'Camera'
                   and l.to_node == 'CameraInfo' for l in links)
        assert any(l.from_node == 'CameraInfo' and l.from_output == 'Rotation'
                   and l.to_node == 'FaceCamera' for l in links)
        assert any(l.from_node == 'RollRot' and l.to_node == 'FaceCamera'
                   and l.to_input == 'Rotate By' for l in links)
        assert any(l.from_node == 'FaceCamera' and l.to_node == 'Billboards'
                   and l.to_input == 'Rotation' for l in links)


class TestColorRamp:

    def _ramp(self, stops):
        br = _plan(_system([_emitter(color_over_life=stops)]))
        return br.emitters[0].node_group.color_ramps['ColorOverLife']

    def test_constant_colour_becomes_flat_white_ramp(self):
        ramp = self._ramp([])
        assert [s.position for s in ramp.stops] == [0.0, 1.0]
        assert all(s.color == (1.0, 1.0, 1.0, 1.0) for s in ramp.stops)

    def test_stops_linearised_with_alpha_untouched(self):
        ramp = self._ramp([IRColorStop(age=0.0, rgba=(0.5, 0.25, 0.75, 0.5))])
        assert ramp.stops[0].color == pytest.approx(
            (srgb_to_linear(0.5), srgb_to_linear(0.25), srgb_to_linear(0.75), 0.5))

    def test_coincident_ages_nudged_apart(self):
        ramp = self._ramp([IRColorStop(age=0.5, rgba=(1.0, 0.0, 0.0, 1.0)),
                           IRColorStop(age=0.5, rgba=(0.0, 1.0, 0.0, 1.0)),
                           IRColorStop(age=0.5, rgba=(0.0, 0.0, 1.0, 1.0))])
        positions = [s.position for s in ramp.stops]
        assert len(positions) == 3
        assert all(b > a for a, b in zip(positions, positions[1:]))

    def test_saturated_run_keeps_the_last_colour(self):
        red, green = (1.0, 0.0, 0.0, 1.0), (0.0, 1.0, 0.0, 1.0)
        ramp = self._ramp([IRColorStop(age=1.0, rgba=red),
                           IRColorStop(age=1.0, rgba=green)])
        assert [s.position for s in ramp.stops] == [1.0]
        assert ramp.stops[0].color == pytest.approx(
            (srgb_to_linear(0.0), srgb_to_linear(1.0), 0.0, 1.0))

    def test_capped_at_blender_ceiling(self):
        stops = [IRColorStop(age=i / 99.0, rgba=(1.0, 1.0, 1.0, 1.0))
                 for i in range(100)]
        ramp = self._ramp(stops)
        assert len(ramp.stops) == 32
        assert ramp.stops[0].position == 0.0
        assert ramp.stops[-1].position == 1.0

    def test_positions_clamped_to_unit_range(self):
        ramp = self._ramp([IRColorStop(age=-0.5, rgba=(1.0, 1.0, 1.0, 1.0)),
                           IRColorStop(age=2.0, rgba=(1.0, 1.0, 1.0, 1.0))])
        assert [s.position for s in ramp.stops] == [0.0, 1.0]


class TestSizeCurve:

    def _curve(self, keys, birth=None):
        emitter = _emitter(size_over_life=keys,
                           birth=birth or IRParticleBirth())
        br = _plan(_system([emitter]))
        return br.emitters[0].node_group.float_curves['SizeOverLife']

    def test_constant_size_becomes_flat_curve_at_birth_size(self):
        curve = self._curve([], birth=IRParticleBirth(size=IRRandomScalar(base=0.3)))
        assert [(p.x, p.y) for p in curve.points] == [
            (0.0, pytest.approx(0.3)),
            (1.0, pytest.approx(0.3)),
        ]

    def test_values_carry_over_in_world_units(self):
        curve = self._curve([IRScalarKey(age=0.0, value=0.1),
                             IRScalarKey(age=1.0, value=0.4)])
        assert curve.points[0].y == pytest.approx(0.1)
        assert curve.points[1].y == pytest.approx(0.4)

    def test_clip_box_widened_to_curve_range(self):
        curve = self._curve([IRScalarKey(age=0.0, value=0.0),
                             IRScalarKey(age=1.0, value=5.0)])
        assert curve.clip_max_y == pytest.approx(5.0)
        assert curve.clip_min_y == 0.0

    def test_clip_box_keeps_unit_default_for_small_curves(self):
        curve = self._curve([IRScalarKey(age=0.0, value=0.1),
                             IRScalarKey(age=1.0, value=0.2)])
        assert curve.clip_max_y == 1.0

    def test_negative_values_widen_the_floor(self):
        curve = self._curve([IRScalarKey(age=0.0, value=-0.5),
                             IRScalarKey(age=1.0, value=1.0)])
        assert curve.clip_min_y == pytest.approx(-0.5)

    def test_points_strictly_increasing(self):
        curve = self._curve([IRScalarKey(age=0.25, value=1.0),
                             IRScalarKey(age=0.25, value=2.0),
                             IRScalarKey(age=0.25, value=3.0)])
        xs = [p.x for p in curve.points]
        assert all(b > a for a, b in zip(xs, xs[1:]))


class TestCustomProps:

    def test_emitter_index_recorded(self):
        br = _plan(_system([_emitter(name='G00'), _emitter(name='G01')]))
        assert br.emitters[0].custom_props['dat_particle_emitter_index'] == 0
        assert br.emitters[1].custom_props['dat_particle_emitter_index'] == 1

    def test_empty_lists_omitted(self):
        props = _plan().emitters[0].custom_props
        assert set(props) == {'dat_particle_emitter_index'}

    def test_flipbook_arrays(self):
        texture = IRParticleTextureAnim(frames=(0, 2, 1),
                                        frame_ages=(0.0, 0.5, 0.75))
        props = _plan(_system([_emitter(texture=texture)])).emitters[0].custom_props
        assert props['dat_particle_flipbook_frames'] == [0, 2, 1]
        assert props['dat_particle_flipbook_ages'] == [0.0, 0.5, 0.75]

    def test_sub_emitters_flattened_to_parallel_arrays(self):
        subs = [IRSubEmitter(age=0.0, emitter_ref=3, count=2, inherit_velocity=True),
                IRSubEmitter(age=1.0, emitter_ref=5, count=1, inherit_velocity=False)]
        props = _plan(_system([_emitter(sub_emitters=subs)])).emitters[0].custom_props
        assert props['dat_particle_sub_ages'] == [0.0, 1.0]
        assert props['dat_particle_sub_refs'] == [3, 5]
        assert props['dat_particle_sub_counts'] == [2, 1]
        assert props['dat_particle_sub_inherit'] == [1, 0]

    def test_bursts_flattened(self):
        emission = IRParticleEmission(rate=0.0, bursts=((0.0, 10), (5.0, 3)))
        props = _plan(_system([_emitter(emission=emission)])).emitters[0].custom_props
        assert props['dat_particle_burst_frames'] == [0.0, 5.0]
        assert props['dat_particle_burst_counts'] == [10, 3]


class TestEmitterMaterial:

    def _material(self, emitter, textures=None):
        textures = textures if textures is not None else [
            IRParticleTexture(width=2, height=2, pixels=b'\xff' * 16)]
        return _plan(_system([emitter], textures)).emitters[0].material

    def test_untextured_emitter_is_tinted_emission(self):
        material = self._material(_emitter(render=IRParticleRender(textured=False)))
        assert isinstance(material, BRMaterial)
        assert _node_types(material) == {
            'ShaderNodeAttribute', 'ShaderNodeEmission', 'ShaderNodeBsdfTransparent',
            'ShaderNodeMixShader', 'ShaderNodeOutputMaterial'}
        # The per-particle colour still drives both the tint and the fade.
        links = material.node_graph.links
        assert any(l.from_node == 'ParticleColor' and l.to_node == 'ParticleEmission'
                   for l in links)
        assert any(l.from_node == 'ParticleColor' and l.to_node == 'ParticleAlphaMix'
                   for l in links)

    def test_textured_emitter_mixes_alpha_against_transparent(self):
        emitter = _emitter(texture=IRParticleTextureAnim(frames=(0,), frame_ages=(0.0,)))
        material = self._material(emitter)
        assert _node_types(material) == {
            'ShaderNodeTexImage', 'ShaderNodeEmission', 'ShaderNodeBsdfTransparent',
            'ShaderNodeMixShader', 'ShaderNodeOutputMaterial',
            'ShaderNodeAttribute', 'ShaderNodeMixRGB', 'ShaderNodeMath'}
        assert material.blend_method == 'BLEND'

    def test_texture_is_multiplied_by_the_particle_colour(self):
        emitter = _emitter(texture=IRParticleTextureAnim(frames=(0,), frame_ages=(0.0,)))
        material = self._material(emitter)
        tint = next(n for n in material.node_graph.nodes if n.name == 'ParticleTint')
        assert tint.properties['blend_type'] == 'MULTIPLY'
        sources = {l.from_node for l in material.node_graph.links
                   if l.to_node == 'ParticleTint'}
        assert sources == {'ParticleTexture', 'ParticleColor'}

    def test_particle_colour_reads_the_instancer_attribute(self):
        material = self._material(_emitter())
        attr = next(n for n in material.node_graph.nodes if n.name == 'ParticleColor')
        assert attr.properties['attribute_type'] == 'GEOMETRY'
        assert attr.properties['attribute_name'] == 'particle_color'

    def test_texture_node_binds_the_first_flipbook_frame(self):
        emitter = _emitter(texture=IRParticleTextureAnim(frames=(1, 0),
                                                         frame_ages=(0.0, 0.5)))
        textures = [IRParticleTexture(width=2, height=2, pixels=b'\x01' * 16),
                    IRParticleTexture(width=2, height=2, pixels=b'\x02' * 16)]
        material = self._material(emitter, textures)
        tex_node = next(n for n in material.node_graph.nodes
                        if n.node_type == 'ShaderNodeTexImage')
        assert tex_node.image_ref.name == 'DATPlugin_ParticleTex_pika_T01'

    def test_out_of_range_frame_falls_back_to_untextured(self):
        emitter = _emitter(texture=IRParticleTextureAnim(frames=(7,), frame_ages=(0.0,)))
        material = self._material(emitter)
        assert 'ShaderNodeTexImage' not in _node_types(material)

    def test_filter_and_wrap_land_on_the_texture_node(self):
        emitter = _emitter(texture=IRParticleTextureAnim(
            frames=(0,), frame_ages=(0.0,), filter='NEAREST',
            wrap_s='MIRROR', wrap_t='MIRROR'))
        material = self._material(emitter)
        tex_node = next(n for n in material.node_graph.nodes
                        if n.node_type == 'ShaderNodeTexImage')
        assert tex_node.properties['interpolation'] == 'Closest'
        assert tex_node.properties['extension'] == 'MIRROR'

    def test_materials_dedup_keys_differ_per_emitter(self):
        br = _plan(_system([_emitter(name='G00'), _emitter(name='G01')]))
        assert br.emitters[0].material.dedup_key != br.emitters[1].material.dedup_key


class TestValueHelpers:

    def test_extension_prefers_mirror_when_either_axis_mirrors(self):
        assert _extension_for(IRParticleTextureAnim(wrap_s='MIRROR')) == 'MIRROR'
        assert _extension_for(IRParticleTextureAnim(wrap_t='MIRROR')) == 'MIRROR'
        assert _extension_for(IRParticleTextureAnim()) == 'EXTEND'

    def test_downsample_keeps_endpoints(self):
        items = list(range(100))
        picked = _downsample([IRScalarKey(age=i / 99.0, value=i) for i in items], 10)
        assert len(picked) == 10
        assert picked[0].value == 0
        assert picked[-1].value == 99

    def test_downsample_passes_short_lists_through(self):
        keys = [IRScalarKey(age=0.0), IRScalarKey(age=1.0)]
        assert _downsample(keys, 32) == keys

    def test_lay_out_returns_position_key_pairs(self):
        keys = [IRScalarKey(age=0.0), IRScalarKey(age=0.5), IRScalarKey(age=1.0)]
        assert [p for p, _ in _lay_out(keys)] == [0.0, 0.5, 1.0]

    def test_lay_out_handles_unordered_input(self):
        keys = [IRScalarKey(age=0.75), IRScalarKey(age=0.25)]
        positions = [p for p, _ in _lay_out(keys)]
        assert positions[1] > positions[0]
