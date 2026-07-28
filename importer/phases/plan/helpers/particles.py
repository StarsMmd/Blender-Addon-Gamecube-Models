"""IR particles → BR particles conversion.

Pure — no bpy. Owns every Blender-side decision about how a semantic
emitter is represented: GC→meter scaling, Y-up→Z-up axis flips, sRGB→linear
colours, the node-group interface (which parameter becomes which socket
type), ColorRamp / Float-Curve layout, the emitter material graph, and the
flat custom-prop arrays that carry list-valued content Blender has no
native slot for.

The build phase replays the result mechanically: one Empty per system, one
single-vertex mesh per emitter, each with a Geometry Nodes modifier whose
group exposes the emitter's parameters.
"""
import math

try:
    from .....shared.BR.particles import (
        BRInterfaceSocket, BRColorRamp, BRColorRampStop, BRCurvePoint,
        BRFloatCurve, BRParticleNodeGroup, BRParticleEmitter, BRParticleSystem,
        BRParticleAttach, BRParticleEmitDriver,
    )
    from .....shared.BR.materials import BRImage, BRMaterial
    from .....shared.helpers.logger import StubLogger
    from .....shared.helpers.scale import GC_TO_METERS
    from .....shared.helpers.srgb import srgb_to_linear
    from .animations import particle_emit_lane_widths
    from .materials import BRGraphBuilder
except (ImportError, SystemError):
    from shared.BR.particles import (
        BRInterfaceSocket, BRColorRamp, BRColorRampStop, BRCurvePoint,
        BRFloatCurve, BRParticleNodeGroup, BRParticleEmitter, BRParticleSystem,
        BRParticleAttach, BRParticleEmitDriver,
    )
    from shared.BR.materials import BRImage, BRMaterial
    from shared.helpers.logger import StubLogger
    from shared.helpers.scale import GC_TO_METERS
    from shared.helpers.srgb import srgb_to_linear
    from importer.phases.plan.helpers.animations import particle_emit_lane_widths
    from importer.phases.plan.helpers.materials import BRGraphBuilder


# Blender's ColorRamp holds at most 32 elements.
_MAX_RAMP_STOPS = 32

# Minimum gap between successive ramp stops / curve points. The source
# encoding produces coincident keys (a snapped ramp re-anchors its stop onto
# the cursor); Blender needs strictly increasing positions to keep both.
_MIN_STEP = 1e-4

# Render-mode enums as menu ints on the node-group interface.
_BLEND_MODES = ('ALPHA', 'ADD', 'MULTIPLY')
_BILLBOARDS = ('CAMERA', 'VELOCITY_STRETCH', 'NONE')

_RAMP_NODE = 'ColorOverLife'
_CURVE_NODE = 'SizeOverLife'


def plan_particles(ir_particles, model_name, bone_animations=(),
                   logger=StubLogger()):
    """Convert an IRParticleSystem into a BRParticleSystem.

    In: ir_particles (IRParticleSystem|None); model_name (str, used to build
        object/node-group/image names); bone_animations
        (iterable[IRBoneAnimationSet] — scanned for the spawn events that say
        which bone each emitter fires from); logger (Logger).
    Out: BRParticleSystem|None — None when there is no particle data, so the
         build phase skips the whole leg.
    """
    if ir_particles is None or not ir_particles.emitters:
        return None

    images = [_plan_texture_image(tex, i, model_name)
              for i, tex in enumerate(ir_particles.textures)]

    firing_bones = _firing_bones(bone_animations)
    lane_widths = particle_emit_lane_widths(bone_animations or ())
    attaches = [BRParticleAttach(name="Particles_%s_Attach_%s" % (model_name, bone),
                                 bone_name=bone)
                for bone in sorted({b for bones in firing_bones.values()
                                    for b in bones})]
    attach_by_bone = {a.bone_name: a.name for a in attaches}

    emitters = [
        _plan_emitter(em, i, model_name, images,
                      _firing_bone(i, firing_bones), attach_by_bone, lane_widths)
        for i, em in enumerate(ir_particles.emitters)
    ]

    logger.debug("    Planned %d particle emitter(s), %d texture(s), %d attach point(s)",
                 len(emitters), len(images), len(attaches))

    return BRParticleSystem(
        root_name="Particles_%s" % model_name,
        emitters=emitters,
        images=images,
        attaches=attaches,
    )


def _firing_bones(bone_animations):
    """Count, per emitter, how often each bone fires it across every clip.

    In: bone_animations (iterable[IRBoneAnimationSet]).
    Out: dict[int, dict[str, int]] — emitter index → {bone name: event count}.
    """
    counts = {}
    for anim_set in bone_animations or ():
        for track in anim_set.tracks:
            for event in track.particle_emits:
                per_bone = counts.setdefault(event.emitter_ref, {})
                per_bone[track.bone_name] = per_bone.get(track.bone_name, 0) + 1
    return counts


def _firing_bone(index, firing_bones):
    """Pick the bone an emitter previews from.

    An emitter fired from several bones has no single spawn site — the game
    makes one generator instance per firing event. The preview shows the
    busiest of them (ties broken by name so the choice is stable); the
    authoritative binding stays on the bones' emit fcurves either way.

    In: index (int, emitter slot); firing_bones (dict[int, dict[str, int]]).
    Out: str|None — bone name, None when no clip fires this emitter.
    """
    per_bone = firing_bones.get(index)
    if not per_bone:
        return None
    return min(per_bone, key=lambda name: (-per_bone[name], name))


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


def _plan_emitter(em, index, model_name, images, bone_name, attach_by_bone,
                  lane_widths):
    """Convert one IRParticleEmitter into a BRParticleEmitter.

    In: em (IRParticleEmitter); index (int, emitter slot — the value emit
        fcurves carry); model_name (str); images (list[BRImage], system-wide);
        bone_name (str|None, the bone whose clips fire this emitter);
        attach_by_bone (dict[str, str]); lane_widths (dict[str, int]).
    Out: BRParticleEmitter.
    """
    suffix = em.name or ("G%02d" % index)
    attach_name = attach_by_bone.get(bone_name) if bone_name else None
    emit_driver = (BRParticleEmitDriver(bone_name=bone_name,
                                        lane_count=max(1, lane_widths.get(bone_name, 1)),
                                        emitter_index=index)
                   if bone_name else None)
    graph, zones = _plan_simulation_graph()
    group = BRParticleNodeGroup(
        name="DATPlugin_Particles_%s_%s" % (model_name, suffix),
        inputs=_plan_interface_inputs(em, attach_name, emit_driver is None),
        outputs=[BRInterfaceSocket(name='Geometry', socket_type='NodeSocketGeometry')],
        nodes=graph.nodes,
        links=graph.links,
        color_ramps={_RAMP_NODE: _plan_color_ramp(em)},
        float_curves={_CURVE_NODE: _plan_size_curve(em)},
        simulation_zones=zones,
    )
    return BRParticleEmitter(
        name="Particles_%s_%s" % (model_name, suffix),
        node_group=group,
        material=_plan_emitter_material(em, "DATPlugin_ParticleMat_%s_%s"
                                        % (model_name, suffix), images),
        custom_props=_plan_custom_props(em, index),
        attach_name=attach_name,
        emit_driver=emit_driver,
    )


def _plan_interface_inputs(em, attach_name=None, always_emit=True):
    """Lay out the emitter's scalar parameters as node-group interface sockets.

    Vectors arrive Y-up in metres (positions/velocities) or GC units (sizes);
    both are converted here. Enum-valued render state becomes a bounded int
    socket so it shows as a plain numeric field on the modifier.

    In: em (IRParticleEmitter); attach_name (str|None, object the preview
        spawns at — the Empty on the bone that fires this emitter);
        always_emit (bool, True when nothing fires this emitter so no driver
        will gate it).
    Out: list[BRInterfaceSocket], geometry input first.
    """
    life, birth, rot = em.particle_lifetime, em.birth, em.rotation
    render, forces = em.render, em.forces
    return [
        BRInterfaceSocket('Geometry', 'NodeSocketGeometry'),
        BRInterfaceSocket('Attach', 'NodeSocketObject', value=attach_name,
                          description='Bone this emitter fires from. Particles '
                                      'spawn at it and then follow their own '
                                      'path, as the game attaches a generator '
                                      'instance to the firing bone.'),
        _float('Emit', 1.0 if always_emit else 0.0, subtype='FACTOR',
               min_value=0.0, max_value=1.0,
               description='Whether the emitter is currently spawning. Driven '
                           'by the firing bone\'s particle_emit keys, so a clip '
                           'runs the emitters it actually fires.'),

        _float('Emit Duration', em.emit_duration, min_value=0.0,
               description='Frames the emitter keeps spawning'),
        _int('Max Particles', em.max_particles, min_value=0),
        _float('Emission Rate', em.emission.rate, min_value=0.0,
               description='Particles spawned per frame'),
        _float('Lifetime', life.base, min_value=0.0,
               description='Particle life in frames'),
        _float('Lifetime Spread', life.spread, min_value=0.0),
        _bool('Looping', em.looping,
              description='Per-particle animation repeats until death'),

        _vector('Birth Position', _gc_to_blender(birth.position.base), 'TRANSLATION'),
        _vector('Birth Position Spread', _spread_to_blender(birth.position.spread),
                'TRANSLATION'),
        _vector('Birth Velocity', _gc_to_blender(birth.velocity.base), 'VELOCITY'),
        _vector('Birth Velocity Spread', _spread_to_blender(birth.velocity.spread),
                'VELOCITY'),
        _float('Birth Size', birth.size.base * GC_TO_METERS, subtype='DISTANCE'),
        _float('Birth Size Spread', birth.size.spread * GC_TO_METERS,
               subtype='DISTANCE', min_value=0.0),
        _color('Color Spread', tuple(birth.color_spread),
               description='Per-channel +/- randomisation of the birth colour'),

        _float('Rotation', rot.initial.base, subtype='ANGLE'),
        _float('Rotation Spread', rot.initial.spread, subtype='ANGLE', min_value=0.0),
        _float('Rotation Rate', rot.rate.base, subtype='ANGLE',
               description='Radians per frame'),
        _float('Rotation Rate Spread', rot.rate.spread, subtype='ANGLE', min_value=0.0),
        _float('Rotation Accel', rot.accel, subtype='ANGLE'),

        _vector('Gravity', _gc_to_blender(forces.gravity), 'ACCELERATION'),
        _float('Drag', forces.drag, subtype='FACTOR', min_value=0.0, max_value=1.0),

        _int('Blend Mode', _enum_index(_BLEND_MODES, render.blend_mode),
             min_value=0, max_value=len(_BLEND_MODES) - 1,
             description='0 alpha, 1 add, 2 multiply'),
        _int('Billboard', _enum_index(_BILLBOARDS, render.billboard),
             min_value=0, max_value=len(_BILLBOARDS) - 1,
             description='0 camera-facing, 1 velocity-stretched, 2 none'),
        _bool('Textured', render.textured),
        _bool('Depth Test', render.depth_test),
        _float('Trail Length', render.trail_length, subtype='DISTANCE', min_value=0.0),
    ]


def _plan_custom_props(em, index):
    """Flatten list-valued emitter content into custom-prop arrays.

    Blender has no native slot for a flip-book schedule, sub-emitter
    triggers, or emission bursts, and IDProperty arrays hold only scalars —
    so each list becomes parallel flat arrays. Empty lists are omitted
    (Blender rejects empty-sequence custom props).

    In: em (IRParticleEmitter); index (int, emitter slot).
    Out: dict[str, object] — custom props for the emitter object.
    """
    props = {'dat_particle_emitter_index': index}

    if em.texture.frames:
        props['dat_particle_flipbook_frames'] = [int(f) for f in em.texture.frames]
        props['dat_particle_flipbook_ages'] = [float(a) for a in em.texture.frame_ages]

    if em.emission.bursts:
        props['dat_particle_burst_frames'] = [float(f) for f, _ in em.emission.bursts]
        props['dat_particle_burst_counts'] = [int(c) for _, c in em.emission.bursts]

    if em.sub_emitters:
        props['dat_particle_sub_ages'] = [float(s.age) for s in em.sub_emitters]
        props['dat_particle_sub_refs'] = [int(s.emitter_ref) for s in em.sub_emitters]
        props['dat_particle_sub_counts'] = [int(s.count) for s in em.sub_emitters]
        props['dat_particle_sub_inherit'] = [int(bool(s.inherit_velocity))
                                             for s in em.sub_emitters]
    return props


# ---------------------------------------------------------------------------
# Node group contents
# ---------------------------------------------------------------------------


# Per-point attributes the simulation carries between frames. They live on the
# points themselves rather than as zone state items, so they survive the join
# with each frame's newly spawned points.
_VELOCITY_ATTR = 'velocity'
_AGE_ATTR = 'age'
# Written for the shader to tint each particle; read back through an INSTANCER
# Attribute node, since the quads are instances of one mesh.
_COLOR_ATTR = 'particle_color'

_INPUT = 'Group Input'
_OUTPUT = 'Group Output'
_SIM_IN = 'SimulationInput'
_SIM_OUT = 'SimulationOutput'
_MATERIAL_NODE = 'ParticleMaterial'


def _plan_simulation_graph():
    """Build the emitter's whole geometry-node graph.

    Three stages, chained: spawn this frame's points at the attach object,
    run them through a simulation zone that integrates velocity and ages
    them out, then instance a textured cross-quad per surviving particle,
    scaled by the size curve and tinted by the colour ramp.

    Both over-life nodes are the *same* editable nodes the export leg reads
    back — the preview samples them rather than keeping its own copy.

    In: ().
    Out: (BRNodeGraph, list[tuple[str, str]]) — graph plus the simulation
         zone's (input node, output node) pair.
    """
    g = BRGraphBuilder()
    g.add_node('NodeGroupInput', name=_INPUT, location=(-1400.0, 0.0))

    # Shared by both stages: a zero-frame lifetime would divide by zero when
    # normalising age and retire every particle on the frame it was born.
    g.add_node('ShaderNodeMath', name='SafeLifetime',
               properties={'operation': 'MAXIMUM'},
               input_defaults={'Value_001': 1.0}, location=(-1150.0, -450.0))
    g.add_link(_INPUT, 'Lifetime', 'SafeLifetime', 'Value')

    spawned = _plan_spawn_stage(g)
    simulated = _plan_simulation_stage(g, spawned)
    rendered = _plan_render_stage(g, simulated)

    g.add_node('NodeGroupOutput', name=_OUTPUT, location=(1400.0, 0.0))
    g.add_link(rendered, 'Geometry', _OUTPUT, 'Geometry')

    return g.finalize(), [(_SIM_IN, _SIM_OUT)]


def _plan_spawn_stage(g):
    """Emit this frame's new particles at the attach object.

    Positions and velocities are drawn per point inside the emitter's own
    space: the attach object's *relative* transform places the spawn, so
    particles born there keep their own world path afterwards instead of
    riding along with the bone.

    In: g (BRGraphBuilder, mutated).
    Out: str — name of the node whose Geometry output is the new points.
    """
    g.add_node('GeometryNodeInputSceneTime', name='SceneTime', location=(-1400.0, -700.0))
    g.add_node('GeometryNodeObjectInfo', name='AttachInfo',
               properties={'transform_space': 'RELATIVE'}, location=(-1150.0, 260.0))
    g.add_link(_INPUT, 'Attach', 'AttachInfo', 'Object')

    # Uniform in [-spread, +spread] around the authored base value.
    for row, (label, source) in enumerate((('Pos', 'Birth Position'),
                                           ('Vel', 'Birth Velocity'))):
        spread = '%s Spread' % source
        height = -120.0 - row * 300.0
        g.add_node('ShaderNodeVectorMath', name='%sSpreadNeg' % label,
                   properties={'operation': 'SCALE'},
                   input_defaults={'Scale': -1.0}, location=(-1150.0, height))
        g.add_link(_INPUT, spread, '%sSpreadNeg' % label, 'Vector')

        g.add_node('FunctionNodeRandomValue', name='%sRandom' % label,
                   properties={'data_type': 'FLOAT_VECTOR'},
                   location=(-900.0, height))
        g.add_link('%sSpreadNeg' % label, 'Vector', '%sRandom' % label, 'Min')
        g.add_link(_INPUT, spread, '%sRandom' % label, 'Max')
        g.add_link('SceneTime', 'Frame', '%sRandom' % label, 'Seed')

        g.add_node('ShaderNodeVectorMath', name='%sBirth' % label,
                   properties={'operation': 'ADD'}, location=(-650.0, height))
        g.add_link(_INPUT, source, '%sBirth' % label, 'Vector')
        g.add_link('%sRandom' % label, 'Value', '%sBirth' % label, 'Vector_001')

    g.add_node('ShaderNodeVectorMath', name='SpawnPosition',
               properties={'operation': 'ADD'}, location=(-400.0, 200.0))
    g.add_link('AttachInfo', 'Location', 'SpawnPosition', 'Vector')
    g.add_link('PosBirth', 'Vector', 'SpawnPosition', 'Vector_001')

    # The Count socket is an integer, so a rate below one particle per frame
    # would truncate to no emission at all; round up instead so slow emitters
    # still show something.
    g.add_node('ShaderNodeMath', name='SpawnCount',
               properties={'operation': 'CEIL'}, location=(-650.0, 380.0))
    g.add_link(_INPUT, 'Emission Rate', 'SpawnCount', 'Value')

    # Emit is 0 while the clip isn't firing this emitter, which stops spawning
    # without disturbing the particles already alive.
    g.add_node('ShaderNodeMath', name='GatedCount',
               properties={'operation': 'MULTIPLY'}, location=(-400.0, 380.0))
    g.add_link('SpawnCount', 'Value', 'GatedCount', 'Value')
    g.add_link(_INPUT, 'Emit', 'GatedCount', 'Value_001')

    g.add_node('GeometryNodePoints', name='SpawnPoints', location=(-150.0, 300.0))
    g.add_link('GatedCount', 'Value', 'SpawnPoints', 'Count')
    g.add_link('SpawnPosition', 'Vector', 'SpawnPoints', 'Position')

    g.add_node('GeometryNodeStoreNamedAttribute', name='StoreBirthVelocity',
               properties={'data_type': 'FLOAT_VECTOR', 'domain': 'POINT'},
               input_defaults={'Name': _VELOCITY_ATTR}, location=(100.0, 300.0))
    g.add_link('SpawnPoints', 'Geometry', 'StoreBirthVelocity', 'Geometry')
    g.add_link('VelBirth', 'Vector', 'StoreBirthVelocity', 'Value')

    g.add_node('GeometryNodeStoreNamedAttribute', name='StoreBirthAge',
               properties={'data_type': 'FLOAT', 'domain': 'POINT'},
               input_defaults={'Name': _AGE_ATTR, 'Value': 0.0},
               location=(350.0, 300.0))
    g.add_link('StoreBirthVelocity', 'Geometry', 'StoreBirthAge', 'Geometry')
    return 'StoreBirthAge'


def _plan_simulation_stage(g, spawned):
    """Carry particles across frames: integrate, age, and retire them.

    In: g (BRGraphBuilder, mutated); spawned (str, node emitting this frame's
        new points).
    Out: str — name of the node whose Geometry output is the live particles.
    """
    g.add_node('GeometryNodeSimulationInput', name=_SIM_IN, location=(600.0, 0.0))
    g.add_node('GeometryNodeSimulationOutput', name=_SIM_OUT, location=(1150.0, 0.0))

    g.add_node('GeometryNodeJoinGeometry', name='AddSpawned', location=(750.0, 0.0))
    g.add_link(_SIM_IN, 'Item_0', 'AddSpawned', 'Geometry')
    g.add_link(spawned, 'Geometry', 'AddSpawned', 'Geometry')

    g.add_node('GeometryNodeInputNamedAttribute', name='ReadVelocity',
               properties={'data_type': 'FLOAT_VECTOR'},
               input_defaults={'Name': _VELOCITY_ATTR}, location=(600.0, -300.0))
    g.add_node('GeometryNodeInputNamedAttribute', name='ReadAge',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Name': _AGE_ATTR}, location=(600.0, -450.0))

    # velocity = velocity * (1 - drag) + gravity
    g.add_node('ShaderNodeMath', name='DragFactor',
               properties={'operation': 'SUBTRACT'},
               input_defaults={'Value': 1.0}, location=(750.0, -300.0))
    g.add_link(_INPUT, 'Drag', 'DragFactor', 'Value_001')

    g.add_node('ShaderNodeVectorMath', name='Damped',
               properties={'operation': 'SCALE'}, location=(850.0, -300.0))
    g.add_link('ReadVelocity', 'Attribute', 'Damped', 'Vector')
    g.add_link('DragFactor', 'Value', 'Damped', 'Scale')

    g.add_node('ShaderNodeVectorMath', name='NextVelocity',
               properties={'operation': 'ADD'}, location=(950.0, -300.0))
    g.add_link('Damped', 'Vector', 'NextVelocity', 'Vector')
    g.add_link(_INPUT, 'Gravity', 'NextVelocity', 'Vector_001')

    g.add_node('GeometryNodeStoreNamedAttribute', name='StoreVelocity',
               properties={'data_type': 'FLOAT_VECTOR', 'domain': 'POINT'},
               input_defaults={'Name': _VELOCITY_ATTR}, location=(850.0, 0.0))
    g.add_link('AddSpawned', 'Geometry', 'StoreVelocity', 'Geometry')
    g.add_link('NextVelocity', 'Vector', 'StoreVelocity', 'Value')

    g.add_node('GeometryNodeSetPosition', name='Advance', location=(950.0, 0.0))
    g.add_link('StoreVelocity', 'Geometry', 'Advance', 'Geometry')
    g.add_link('NextVelocity', 'Vector', 'Advance', 'Offset')

    # Velocities are per frame, so a particle's age advances by one per step.
    g.add_node('ShaderNodeMath', name='NextAge', properties={'operation': 'ADD'},
               input_defaults={'Value_001': 1.0}, location=(750.0, -450.0))
    g.add_link('ReadAge', 'Attribute', 'NextAge', 'Value')

    g.add_node('GeometryNodeStoreNamedAttribute', name='StoreAge',
               properties={'data_type': 'FLOAT', 'domain': 'POINT'},
               input_defaults={'Name': _AGE_ATTR}, location=(1000.0, 0.0))
    g.add_link('Advance', 'Geometry', 'StoreAge', 'Geometry')
    g.add_link('NextAge', 'Value', 'StoreAge', 'Value')

    g.add_node('ShaderNodeMath', name='Expired',
               properties={'operation': 'GREATER_THAN'}, location=(950.0, -600.0))
    g.add_link('ReadAge', 'Attribute', 'Expired', 'Value')
    g.add_link('SafeLifetime', 'Value', 'Expired', 'Value_001')

    g.add_node('GeometryNodeDeleteGeometry', name='Retire',
               properties={'domain': 'POINT', 'mode': 'ALL'}, location=(1075.0, 0.0))
    g.add_link('StoreAge', 'Geometry', 'Retire', 'Geometry')
    g.add_link('Expired', 'Value', 'Retire', 'Selection')

    g.add_link('Retire', 'Geometry', _SIM_OUT, 'Item_0')
    return _SIM_OUT


def _plan_render_stage(g, simulated):
    """Turn surviving particles into shaded, sized, tinted quads.

    Each particle instances a pair of crossed quads: the source engine draws
    camera-facing billboards, which geometry nodes cannot reproduce without a
    camera to aim at, and a cross reads correctly from any viewing angle.

    In: g (BRGraphBuilder, mutated); simulated (str, node emitting live
        particles).
    Out: str — name of the node whose Geometry output is the final geometry.
    """
    g.add_node('ShaderNodeMath', name='NormalizedAge',
               properties={'operation': 'DIVIDE'}, location=(1150.0, -450.0))
    g.add_link('ReadAge', 'Attribute', 'NormalizedAge', 'Value')
    g.add_link('SafeLifetime', 'Value', 'NormalizedAge', 'Value_001')

    g.add_node('ShaderNodeValToRGB', name=_RAMP_NODE, location=(1150.0, -700.0))
    g.add_link('NormalizedAge', 'Value', _RAMP_NODE, 'Fac')

    g.add_node('ShaderNodeFloatCurve', name=_CURVE_NODE, location=(1150.0, -1000.0))
    g.add_link('NormalizedAge', 'Value', _CURVE_NODE, 'Value')

    g.add_node('GeometryNodeStoreNamedAttribute', name='StoreColor',
               properties={'data_type': 'FLOAT_COLOR', 'domain': 'POINT'},
               input_defaults={'Name': _COLOR_ATTR}, location=(1250.0, 0.0))
    g.add_link(simulated, 'Item_0', 'StoreColor', 'Geometry')
    g.add_link(_RAMP_NODE, 'Color', 'StoreColor', 'Value')

    quad = _plan_cross_quad(g)

    g.add_node('GeometryNodeInstanceOnPoints', name='Billboards',
               location=(1300.0, 0.0))
    g.add_link('StoreColor', 'Geometry', 'Billboards', 'Points')
    g.add_link(quad, 'Geometry', 'Billboards', 'Instance')
    g.add_link(_CURVE_NODE, 'Value', 'Billboards', 'Scale')

    g.add_node('GeometryNodeSetMaterial', name=_MATERIAL_NODE, location=(1350.0, 0.0))
    g.add_link('Billboards', 'Instances', _MATERIAL_NODE, 'Geometry')
    return _MATERIAL_NODE


def _plan_cross_quad(g):
    """Two unit quads at right angles, standing upright.

    In: g (BRGraphBuilder, mutated).
    Out: str — name of the node whose Geometry output is the crossed pair.
    """
    g.add_node('GeometryNodeMeshGrid', name='Quad',
               input_defaults={'Size X': 1.0, 'Size Y': 1.0,
                               'Vertices X': 2, 'Vertices Y': 2},
               location=(1000.0, 400.0))

    for name, rotation in (('QuadFront', (math.pi / 2.0, 0.0, 0.0)),
                           ('QuadSide', (math.pi / 2.0, 0.0, math.pi / 2.0))):
        g.add_node('GeometryNodeTransform', name=name,
                   input_defaults={'Rotation': rotation}, location=(1150.0, 400.0))
        g.add_link('Quad', 'Mesh', name, 'Geometry')

    g.add_node('GeometryNodeJoinGeometry', name='CrossQuad', location=(1250.0, 400.0))
    g.add_link('QuadFront', 'Geometry', 'CrossQuad', 'Geometry')
    g.add_link('QuadSide', 'Geometry', 'CrossQuad', 'Geometry')
    return 'CrossQuad'


def _plan_color_ramp(em):
    """Lay out ``color_over_life`` as a ColorRamp.

    IR stops are sRGB on normalized age; Blender wants linear RGB on
    strictly increasing positions, at most 32 of them. A constant colour
    (empty IR list) becomes a flat two-stop ramp so the node is always
    present and editable.

    In: em (IRParticleEmitter).
    Out: BRColorRamp.
    """
    stops = em.color_over_life
    if not stops:
        white = (1.0, 1.0, 1.0, 1.0)
        return BRColorRamp(stops=[BRColorRampStop(position=0.0, color=white),
                                  BRColorRampStop(position=1.0, color=white)])

    return BRColorRamp(stops=[
        BRColorRampStop(position=position, color=_linearize_rgba(stop.rgba))
        for position, stop in _lay_out(_downsample(stops, _MAX_RAMP_STOPS))
    ])


def _plan_size_curve(em):
    """Lay out ``size_over_life`` as a Float Curve.

    Sizes are absolute quad scales in GC units; they become world units
    here. The clip box is widened to the curve's own range — Blender clamps
    curve values to it, and particle sizes routinely exceed the 0-1 default.
    A constant size (empty IR list) becomes a flat two-point curve.

    In: em (IRParticleEmitter).
    Out: BRFloatCurve.
    """
    points = [BRCurvePoint(x=position, y=key.value * GC_TO_METERS)
              for position, key in _lay_out(_downsample(em.size_over_life,
                                                        _MAX_RAMP_STOPS))]
    if len(points) < 2:
        # A curve needs two points to span the age axis: either the size
        # never changes (no IR keys) or every key collapsed onto one age.
        size = points[0].y if points else em.birth.size.base * GC_TO_METERS
        points = [BRCurvePoint(x=0.0, y=size), BRCurvePoint(x=1.0, y=size)]

    values = [p.y for p in points]
    return BRFloatCurve(
        points=points,
        clip_min_y=min(0.0, min(values)),
        clip_max_y=max(1.0, max(values)),
    )


# ---------------------------------------------------------------------------
# Emitter material
# ---------------------------------------------------------------------------


# GX texture filter → Blender image interpolation.
_INTERPOLATION = {'NEAREST': 'Closest', 'LINEAR': 'Linear'}


def _plan_emitter_material(em, name, images):
    """Build the emitter's material: flat-shaded quad, alpha-blended.

    Particles are unlit in the source engine, so the graph is an Emission
    shader mixed against a Transparent BSDF by the texture's alpha. The
    per-particle colour tint lives on the group's ColorRamp, not here.

    In: em (IRParticleEmitter); name (str, material name);
        images (list[BRImage], system-wide, indexed by flip-book frame).
    Out: BRMaterial.
    """
    g = BRGraphBuilder()
    emission = g.add_node('ShaderNodeEmission', name='ParticleEmission',
                          input_defaults={0: (1.0, 1.0, 1.0, 1.0), 1: 1.0},
                          location=(0.0, 0.0))
    output = g.add_node('ShaderNodeOutputMaterial', name='Output',
                        location=(400.0, 0.0))

    # Each particle's own colour arrives as an instancer attribute — the
    # emitter's ColorRamp writes it per point, and every quad is an instance.
    tint = g.add_node('ShaderNodeAttribute', name='ParticleColor',
                      properties={'attribute_type': 'INSTANCER',
                                  'attribute_name': _COLOR_ATTR},
                      location=(-400.0, -300.0))
    transparent = g.add_node('ShaderNodeBsdfTransparent', name='ParticleTransparent',
                             location=(0.0, 180.0))
    mix = g.add_node('ShaderNodeMixShader', name='ParticleAlphaMix',
                     location=(200.0, 0.0))

    image = _first_frame_image(em, images)
    if image is None:
        color_ref, alpha_ref = (tint, 0), (tint, 3)
    else:
        tex = g.add_node('ShaderNodeTexImage', name='ParticleTexture',
                         properties={
                             'interpolation': _INTERPOLATION.get(em.texture.filter, 'Linear'),
                             'extension': _extension_for(em.texture),
                         },
                         image_ref=image, location=(-400.0, 0.0))
        tinted = g.add_node('ShaderNodeMixRGB', name='ParticleTint',
                            properties={'blend_type': 'MULTIPLY'},
                            input_defaults={0: 1.0}, location=(-160.0, 0.0))
        g.add_link(tex, 0, tinted, 1)
        g.add_link(tint, 0, tinted, 2)

        faded = g.add_node('ShaderNodeMath', name='ParticleAlpha',
                           properties={'operation': 'MULTIPLY'},
                           location=(-160.0, -220.0))
        g.add_link(tex, 1, faded, 0)
        g.add_link(tint, 3, faded, 1)

        color_ref, alpha_ref = (tinted, 0), (faded, 0)

    g.add_link(color_ref[0], color_ref[1], emission, 0)
    g.add_link(alpha_ref[0], alpha_ref[1], mix, 0)
    g.add_link(transparent, 0, mix, 1)
    g.add_link(emission, 0, mix, 2)
    g.add_link(mix, 0, output, 0)

    return BRMaterial(
        name=name,
        node_graph=g.finalize(),
        blend_method='BLEND',
        dedup_key=('particle', name),
    )


def _first_frame_image(em, images):
    """Pick the image the emitter's material samples.

    The flip-book's first frame stands in for the whole sheet — Blender
    binds one image per texture node, and the frame schedule rides on the
    emitter's custom props.

    In: em (IRParticleEmitter); images (list[BRImage]).
    Out: BRImage|None — None when untextured, frame-less, or out of range.
    """
    if not em.render.textured or not em.texture.frames or not images:
        return None
    index = int(em.texture.frames[0])
    if not 0 <= index < len(images):
        return None
    return images[index]


def _extension_for(texture):
    """GX wrap modes → a single Blender image extension.

    Blender's texture node has one extension for both axes, so a
    mixed-axis MIRROR/CLAMP pair collapses to MIRROR.

    In: texture (IRParticleTextureAnim).
    Out: str — 'MIRROR' or 'EXTEND'.
    """
    if 'MIRROR' in (texture.wrap_s, texture.wrap_t):
        return 'MIRROR'
    return 'EXTEND'


def _plan_texture_image(tex, index, model_name):
    """Convert one IRParticleTexture into a BRImage.

    In: tex (IRParticleTexture); index (int); model_name (str).
    Out: BRImage — pixels pass through untouched (already RGBA u8).
    """
    return BRImage(
        name="DATPlugin_ParticleTex_%s_T%02d" % (model_name, index),
        width=tex.width,
        height=tex.height,
        pixels=tex.pixels,
        cache_key=('particle_tex', model_name, index),
    )


# ---------------------------------------------------------------------------
# Socket constructors
# ---------------------------------------------------------------------------


def _float(name, value, subtype=None, min_value=None, max_value=None, description=''):
    """Float interface socket."""
    return BRInterfaceSocket(name, 'NodeSocketFloat', float(value), subtype,
                             min_value, max_value, description)


def _int(name, value, min_value=None, max_value=None, description=''):
    """Int interface socket."""
    return BRInterfaceSocket(name, 'NodeSocketInt', int(value), None,
                             min_value, max_value, description)


def _bool(name, value, description=''):
    """Boolean interface socket."""
    return BRInterfaceSocket(name, 'NodeSocketBool', bool(value),
                             description=description)


def _vector(name, value, subtype=None, description=''):
    """Vector interface socket (Blender-space, Z-up)."""
    return BRInterfaceSocket(name, 'NodeSocketVector', tuple(value), subtype,
                             description=description)


def _color(name, rgba, description=''):
    """Colour interface socket (RGBA)."""
    return BRInterfaceSocket(name, 'NodeSocketColor', tuple(rgba),
                             description=description)


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def _gc_to_blender(xyz):
    """GC Y-up → Blender Z-up: (x, y, z) → (x, -z, y).

    In: xyz (tuple[float, float, float]).
    Out: tuple[float, float, float].
    """
    x, y, z = xyz
    return (x, -z, y)


def _spread_to_blender(xyz):
    """Axis-permute a per-axis magnitude the same way positions flip.

    A spread has no direction, so the sign the position flip introduces is
    dropped: (sx, sy, sz) → (|sx|, |sz|, |sy|).

    In: xyz (tuple[float, float, float]).
    Out: tuple[float, float, float].
    """
    x, y, z = xyz
    return (abs(x), abs(z), abs(y))


def _linearize_rgba(rgba):
    """sRGB → linear per colour channel; alpha passes through.

    In: rgba (tuple[float, float, float, float], sRGB [0, 1]).
    Out: tuple[float, float, float, float].
    """
    return (srgb_to_linear(rgba[0]), srgb_to_linear(rgba[1]),
            srgb_to_linear(rgba[2]), rgba[3])


def _enum_index(names, value):
    """Map an IR enum string onto its menu-int index (unknown → 0).

    In: names (tuple[str]); value (str).
    Out: int.
    """
    return names.index(value) if value in names else 0


def _downsample(items, limit):
    """Thin a key list down to ``limit`` entries, keeping the first and last.

    In: items (list); limit (int, >= 2).
    Out: list — evenly spaced selection, or the input when it already fits.
    """
    if len(items) <= limit:
        return list(items)
    step = (len(items) - 1) / (limit - 1)
    picked = [items[int(round(i * step))] for i in range(limit)]
    picked[-1] = items[-1]
    return picked


def _lay_out(keys):
    """Place age-ordered keys on strictly increasing [0, 1] positions.

    Coincident ages are normal in the source encoding (a ramp snapped by a
    later op re-anchors its stop onto the cursor), and Blender collapses
    equal positions — so each key is pushed one epsilon past its
    predecessor. Once the run saturates at 1.0 there is nowhere left to
    push: the later key replaces the one sitting there, since what a
    particle ends its life on is the last value written.

    In: keys (list, each with an ``age`` in [0, 1], age-ordered).
    Out: list[tuple[float, key]] — positions strictly increasing.
    """
    out = []
    for key in keys:
        position = min(1.0, max(0.0, key.age))
        if out and position <= out[-1][0]:
            position = min(1.0, out[-1][0] + _MIN_STEP)
        if out and position <= out[-1][0]:
            out[-1] = (out[-1][0], key)
            continue
        out.append((position, key))
    return out
