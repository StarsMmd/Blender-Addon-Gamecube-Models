"""IR particles → BR particles conversion.

Pure — no bpy. Owns every Blender-side decision about how a semantic
emitter is represented: sRGB→linear colours, the node-group interface (which parameter becomes which socket
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

    # One preview object per (emitter, firing bone): the source creates a
    # generator instance per firing event, so an emitter fired from two
    # bones burns in both places at once.
    emitters = []
    for i, em in enumerate(ir_particles.emitters):
        bones = sorted(firing_bones.get(i) or ())
        for bone_name in (bones or [None]):
            emitters.append(_plan_emitter(
                em, i, model_name, images, bone_name, attach_by_bone,
                lane_widths, multi_bone=len(bones) > 1))

    logger.debug("    Planned %d emitter instance(s) from %d template(s), "
                 "%d texture(s), %d attach point(s)",
                 len(emitters), len(ir_particles.emitters), len(images),
                 len(attaches))

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


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


def _plan_emitter(em, index, model_name, images, bone_name, attach_by_bone,
                  lane_widths, multi_bone=False):
    """Convert one IRParticleEmitter into a BRParticleEmitter instance.

    In: em (IRParticleEmitter); index (int, emitter slot — the value emit
        fcurves carry); model_name (str); images (list[BRImage], system-wide);
        bone_name (str|None, the bone this instance fires from);
        attach_by_bone (dict[str, str]); lane_widths (dict[str, int]);
        multi_bone (bool — several instances share this template, so names
        carry the bone to stay unique).
    Out: BRParticleEmitter.
    """
    template = em.name or ("G%02d" % index)
    # The material describes the template, not the instance — instances share
    # it (build dedups by name); objects and node groups need unique names.
    suffix = ("%s_%s" % (template, bone_name)) if (multi_bone and bone_name) \
        else template
    attach_name = attach_by_bone.get(bone_name) if bone_name else None
    emit_driver = (BRParticleEmitDriver(bone_name=bone_name,
                                        lane_count=max(1, lane_widths.get(bone_name, 1)),
                                        emitter_index=index)
                   if bone_name else None)
    graph, zones = _plan_simulation_graph(em)
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
                                        % (model_name, template), images),
        custom_props=_plan_custom_props(em, index),
        attach_name=attach_name,
        emit_driver=emit_driver,
    )


def _plan_interface_inputs(em, attach_name=None, always_emit=True):
    """Lay out the emitter's scalar parameters as node-group interface sockets.

    Lengths arrive in metres already — describe scales the source units on
    the way into the IR — so only the Y-up→Z-up flip happens here.
    Enum-valued render state becomes a bounded int socket so it shows as a
    plain numeric field on the modifier.

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
        _int('Max Particles', em.max_particles, min_value=0,
             description='Cap on simultaneously live particles'),
        _float('Emission Rate', em.emission.rate, min_value=0.0,
               description='Mean particles spawned per frame'),
        _bool('Rate Jitter', em.emission.rate_jitter,
              description='Each frame spawns rate x uniform[0, 2] instead of '
                          'exactly the rate'),
        _float('Lifetime', life.base, min_value=0.0,
               description='Particle life in frames'),
        _float('Lifetime Spread', life.spread, min_value=0.0),
        _bool('Looping', em.looping,
              description='Per-particle animation repeats until death'),

        _vector('Birth Position', birth.position.base, 'TRANSLATION'),
        _vector('Birth Position Spread', birth.position.spread, 'TRANSLATION'),
        _vector('Birth Velocity', birth.velocity.base, 'VELOCITY'),
        _vector('Birth Velocity Spread', birth.velocity.spread, 'VELOCITY'),
        _float('Birth Size', birth.size.base, subtype='DISTANCE'),
        _float('Birth Size Spread', birth.size.spread,
               subtype='DISTANCE', min_value=0.0),
        _color('Color Spread', tuple(birth.color_spread),
               description='Per-channel +/- randomisation of the birth colour'),

        _float('Rotation', rot.initial.base, subtype='ANGLE'),
        _float('Rotation Spread', rot.initial.spread, subtype='ANGLE', min_value=0.0),
        _float('Rotation Rate', rot.rate.base, subtype='ANGLE',
               description='Radians per frame'),
        _float('Rotation Rate Spread', rot.rate.spread, subtype='ANGLE', min_value=0.0),
        _float('Rotation Accel', rot.accel, subtype='ANGLE'),

        _vector('Gravity', forces.gravity, 'ACCELERATION',
                description='Acceleration in the emitter frame (Y up, like '
                            'the source); the armature object matrix turns '
                            'it upright on screen'),
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

        BRInterfaceSocket('Camera', 'NodeSocketObject',
                          description='Billboards face this camera. Assigned '
                                      'to the scene camera on import.'),
    ] + _shape_inputs(em.emission.shape)


def _shape_inputs(shape):
    """Interface sockets for the emitter's emission shape.

    Only the active kind's parameters appear — each emitter's node group is
    generated for its own shape, so unused knobs would only mislead.

    In: shape (IREmissionShape).
    Out: list[BRInterfaceSocket].
    """
    common = [_vector('Shape Velocity', shape.velocity, 'VELOCITY',
                      description='Authored emitter-frame velocity; its '
                                  'magnitude is the emission speed')]
    if shape.kind == 'BOX':
        return common + [
            _vector('Box Extents', shape.box_extents, 'TRANSLATION',
                    description='Spawn volume from the emitter origin; a '
                                'negative extent emits on that face only'),
        ]
    if shape.kind == 'SPHERE':
        return common + [
            _float('Radius', shape.radius, subtype='DISTANCE', min_value=0.0),
            _bool('Ring', shape.ring,
                  description='Emit on the shell instead of the volume'),
            _float('Polar Max', shape.polar_max, subtype='ANGLE', min_value=0.0,
                   description='Cap angle from the axis; 0 = full sphere'),
            _float('Radial Speed', shape.radial_speed, subtype='DISTANCE',
                   description='Metres per frame along the spawn direction'),
        ]
    return common + [
        _float('Radius', shape.radius, subtype='DISTANCE', min_value=0.0),
        _bool('Ring', shape.ring,
              description='Emit on the rim instead of the filled disc'),
        _bool('Uniform Area', shape.uniform_area,
              description='Uniform-by-area radius sampling; speed also '
                          'scales with the radius fraction'),
        _float('Cone Angle', shape.cone_angle, subtype='ANGLE', min_value=0.0,
               description='Velocity tilt from the axis at the rim'),
        _float('Arc Start', shape.arc_start, subtype='ANGLE'),
        _float('Arc End', shape.arc_end, subtype='ANGLE',
               description='Azimuth range; both zero = the full circle'),
        _bool('Sweep', shape.sweep,
              description="Space one frame's spawns evenly along the arc"),
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

# Per-point attributes the simulation stores at spawn and reads per frame.
_LIFE_ATTR = 'life'
_ROLL0_ATTR = 'roll0'
_ROLL_RATE_ATTR = 'roll_rate'

_PI = math.pi
_TWO_PI = 2.0 * math.pi

_INPUT = 'Group Input'
_OUTPUT = 'Group Output'
_SIM_IN = 'SimulationInput'
_SIM_OUT = 'SimulationOutput'
_MATERIAL_NODE = 'ParticleMaterial'


def _plan_simulation_graph(em):
    """Build the emitter's whole geometry-node graph.

    Everything runs inside one simulation zone so the spawn cadence and the
    generator's own age persist as zone state alongside the particles:
    an accumulator gains the emission rate each frame and spawns the whole
    part it crosses, gated by the emit signal, the emit duration, and the
    live-particle cap. Newborns take their position and velocity from the
    emission shape, then integrate under gravity and drag until their own
    lifetime retires them. Surviving particles render as camera-facing
    quads scaled by the size curve and tinted by the colour ramp — the
    same editable nodes the export leg reads back.

    In: em (IRParticleEmitter — selects the shape sub-graph and blend).
    Out: (BRNodeGraph, list) — graph plus the simulation-zone spec
         [(input node, output node, [(state type, state name), ...])].
    """
    g = BRGraphBuilder()
    g.add_node('NodeGroupInput', name=_INPUT, location=(-2200.0, 0.0))
    g.add_node('GeometryNodeInputSceneTime', name='SceneTime', location=(-2200.0, -600.0))
    g.add_node('GeometryNodeObjectInfo', name='AttachInfo',
               properties={'transform_space': 'RELATIVE'}, location=(-2200.0, 300.0))
    g.add_link(_INPUT, 'Attach', 'AttachInfo', 'Object')
    g.add_node('GeometryNodeObjectInfo', name='CameraInfo',
               properties={'transform_space': 'RELATIVE'}, location=(-2200.0, 500.0))
    g.add_link(_INPUT, 'Camera', 'CameraInfo', 'Object')

    g.add_node('GeometryNodeSimulationInput', name=_SIM_IN, location=(-1800.0, 0.0))
    g.add_node('GeometryNodeSimulationOutput', name=_SIM_OUT, location=(600.0, 0.0))

    _plan_cadence(g)
    spawned = _plan_spawn(g, em.emission.shape)
    _plan_motion(g, spawned)

    rendered = _plan_render_stage(g)
    g.add_node('NodeGroupOutput', name=_OUTPUT, location=(1600.0, 0.0))
    g.add_link(rendered, 'Geometry', _OUTPUT, 'Geometry')

    zones = [(_SIM_IN, _SIM_OUT, [('FLOAT', 'Acc'), ('FLOAT', 'Age')])]
    return g.finalize(), zones


def _math(g, name, op, location=(0.0, 0.0), defaults=None):
    """Add a Math node; returns its name."""
    return g.add_node('ShaderNodeMath', name=name, properties={'operation': op},
                      input_defaults=defaults or {}, location=location)


def _plan_cadence(g):
    """Spawn-count state machine: accumulator, generator age, and gates.

    The accumulator gains the (optionally jittered) rate each frame and
    spawns the integer part it crosses. It resets while the emitter is
    gated off — matching the source, where an inactive generator is dead
    rather than paused. The generator's age gates emission after Emit
    Duration unless the emitter loops; the live-point count enforces Max
    Particles.

    In: g (BRGraphBuilder, mutated).
    Out: None — terminal nodes are 'SpawnCount', 'AccNext', 'AgeNext'.
    """
    y = -650.0
    # A Random Value node's unlinked ID falls back to an implicit per-element
    # field, which would turn the whole cadence chain into a field and break
    # the single-value spawn count — pin frame-level draws to a constant ID.
    g.add_node('FunctionNodeInputInt', name='SharedID',
               properties={'integer': 0}, location=(-1900.0, y))
    g.add_node('FunctionNodeRandomValue', name='RateJitterRand',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Min_001': 0.0, 'Max_001': 2.0}, location=(-1750.0, y))
    g.add_link('SceneTime', 'Frame', 'RateJitterRand', 'Seed')
    g.add_link('SharedID', 'Integer', 'RateJitterRand', 'ID')

    # rate_eff = Rate x (1 + Jitter x (jrand - 1)) — jitter draws in [0, 2].
    _math(g, 'JitterDelta', 'SUBTRACT', (-1600.0, y), {'Value_001': 1.0})
    g.add_link('RateJitterRand', 'Value_001', 'JitterDelta', 'Value')
    _math(g, 'JitterScale', 'MULTIPLY', (-1450.0, y))
    g.add_link(_INPUT, 'Rate Jitter', 'JitterScale', 'Value')
    g.add_link('JitterDelta', 'Value', 'JitterScale', 'Value_001')
    _math(g, 'JitterFactor', 'ADD', (-1300.0, y), {'Value': 1.0})
    g.add_link('JitterScale', 'Value', 'JitterFactor', 'Value_001')
    _math(g, 'RateEff', 'MULTIPLY', (-1150.0, y))
    g.add_link(_INPUT, 'Emission Rate', 'RateEff', 'Value')
    g.add_link('JitterFactor', 'Value', 'RateEff', 'Value_001')

    # Gates: emitting, within duration (or looping), and under the cap.
    y = -900.0
    _math(g, 'EmitOn', 'GREATER_THAN', (-1750.0, y), {'Value_001': 0.0})
    g.add_link(_INPUT, 'Emit', 'EmitOn', 'Value')
    _math(g, 'AgeOK', 'LESS_THAN', (-1750.0, y - 150.0))
    g.add_link(_SIM_IN, 'Age', 'AgeOK', 'Value')
    g.add_link(_INPUT, 'Emit Duration', 'AgeOK', 'Value_001')
    # looping OR within-duration = L + A - L x A
    _math(g, 'LoopAgeSum', 'ADD', (-1600.0, y - 150.0))
    g.add_link(_INPUT, 'Looping', 'LoopAgeSum', 'Value')
    g.add_link('AgeOK', 'Value', 'LoopAgeSum', 'Value_001')
    _math(g, 'LoopAgeProd', 'MULTIPLY', (-1600.0, y - 300.0))
    g.add_link(_INPUT, 'Looping', 'LoopAgeProd', 'Value')
    g.add_link('AgeOK', 'Value', 'LoopAgeProd', 'Value_001')
    _math(g, 'LoopOrAge', 'SUBTRACT', (-1450.0, y - 150.0))
    g.add_link('LoopAgeSum', 'Value', 'LoopOrAge', 'Value')
    g.add_link('LoopAgeProd', 'Value', 'LoopOrAge', 'Value_001')

    g.add_node('GeometryNodeAttributeDomainSize', name='LiveCount',
               properties={'component': 'POINTCLOUD'}, location=(-1750.0, y - 450.0))
    g.add_link(_SIM_IN, 'Item_0', 'LiveCount', 'Geometry')
    _math(g, 'CountOK', 'LESS_THAN', (-1600.0, y - 450.0))
    g.add_link('LiveCount', 'Point Count', 'CountOK', 'Value')
    g.add_link(_INPUT, 'Max Particles', 'CountOK', 'Value_001')

    _math(g, 'Gate1', 'MULTIPLY', (-1450.0, y - 350.0))
    g.add_link('EmitOn', 'Value', 'Gate1', 'Value')
    g.add_link('LoopOrAge', 'Value', 'Gate1', 'Value_001')
    _math(g, 'SpawnGate', 'MULTIPLY', (-1300.0, y - 350.0))
    g.add_link('Gate1', 'Value', 'SpawnGate', 'Value')
    g.add_link('CountOK', 'Value', 'SpawnGate', 'Value_001')

    # Accumulator: gains the rate while active, drops the spawned whole part,
    # resets to zero while gated off.
    _math(g, 'AccPlus', 'ADD', (-1150.0, y - 200.0))
    g.add_link(_SIM_IN, 'Acc', 'AccPlus', 'Value')
    g.add_link('RateEff', 'Value', 'AccPlus', 'Value_001')
    _math(g, 'AccGated', 'MULTIPLY', (-1000.0, y - 200.0))
    g.add_link('AccPlus', 'Value', 'AccGated', 'Value')
    g.add_link('SpawnGate', 'Value', 'AccGated', 'Value_001')
    _math(g, 'SpawnCount', 'FLOOR', (-850.0, y - 200.0))
    g.add_link('AccGated', 'Value', 'SpawnCount', 'Value')
    # The Points count socket is a strict integer — convert explicitly.
    g.add_node('FunctionNodeFloatToInt', name='SpawnCountInt',
               properties={'rounding_mode': 'FLOOR'}, location=(-700.0, y - 100.0))
    g.add_link('AccGated', 'Value', 'SpawnCountInt', 'Float')
    _math(g, 'AccNext', 'SUBTRACT', (-700.0, y - 200.0))
    g.add_link('AccGated', 'Value', 'AccNext', 'Value')
    g.add_link('SpawnCount', 'Value', 'AccNext', 'Value_001')
    g.add_link('AccNext', 'Value', _SIM_OUT, 'Acc')

    # Generator age: counts frames while the emit signal holds, resets off it.
    _math(g, 'AgeNext0', 'ADD', (-1150.0, y - 550.0), {'Value_001': 1.0})
    g.add_link(_SIM_IN, 'Age', 'AgeNext0', 'Value')
    _math(g, 'AgeNext', 'MULTIPLY', (-1000.0, y - 550.0))
    g.add_link('AgeNext0', 'Value', 'AgeNext', 'Value')
    g.add_link('EmitOn', 'Value', 'AgeNext', 'Value_001')
    g.add_link('AgeNext', 'Value', _SIM_OUT, 'Age')


def _plan_spawn(g, shape):
    """This frame's newborn points, positioned and armed by the shape.

    In: g (BRGraphBuilder, mutated); shape (IREmissionShape).
    Out: str — node whose Geometry output holds the new points.
    """
    g.add_node('GeometryNodePoints', name='SpawnPoints', location=(-550.0, 350.0))
    g.add_link('SpawnCountInt', 'Integer', 'SpawnPoints', 'Count')
    g.add_node('GeometryNodeInputIndex', name='PIndex', location=(-2200.0, -300.0))

    if shape.kind == 'BOX':
        _plan_shape_box(g)
    elif shape.kind == 'SPHERE':
        _plan_shape_sphere(g)
    else:
        _plan_shape_disc(g)

    # The emitter object sits under the armature, whose object matrix already
    # carries the source→Blender conversion — so the simulation works directly
    # in source axes (Y up) and the display transform happens for free. The
    # source also spawns in the world frame, not the bone frame (its emission
    # matrix is identity for file data), so only the attach *location* is used.

    # Bytecode birth offsets/velocity (already Blender-space) join afterwards.
    for tag, base, spread in (('BPos', 'Birth Position', 'Birth Position Spread'),
                              ('BVel', 'Birth Velocity', 'Birth Velocity Spread')):
        g.add_node('ShaderNodeVectorMath', name='%sSpreadNeg' % tag,
                   properties={'operation': 'SCALE'},
                   input_defaults={'Scale': -1.0}, location=(-1750.0, -1900.0))
        g.add_link(_INPUT, spread, '%sSpreadNeg' % tag, 'Vector')
        g.add_node('FunctionNodeRandomValue', name='%sRand' % tag,
                   properties={'data_type': 'FLOAT_VECTOR'}, location=(-1600.0, -1900.0))
        g.add_link('%sSpreadNeg' % tag, 'Vector', '%sRand' % tag, 'Min')
        g.add_link(_INPUT, spread, '%sRand' % tag, 'Max')
        g.add_link('SceneTime', 'Frame', '%sRand' % tag, 'Seed')
        g.add_link('PIndex', 'Index', '%sRand' % tag, 'ID')
        g.add_node('ShaderNodeVectorMath', name='%sFull' % tag,
                   properties={'operation': 'ADD'}, location=(-1450.0, -1900.0))
        g.add_link(_INPUT, base, '%sFull' % tag, 'Vector')
        g.add_link('%sRand' % tag, 'Value', '%sFull' % tag, 'Vector_001')

    g.add_node('ShaderNodeVectorMath', name='SpawnPosWorld',
               properties={'operation': 'ADD'}, location=(-300.0, -200.0))
    g.add_link('PosGC', 'Vector', 'SpawnPosWorld', 'Vector')
    g.add_link('AttachInfo', 'Location', 'SpawnPosWorld', 'Vector_001')
    g.add_node('ShaderNodeVectorMath', name='SpawnPosFull',
               properties={'operation': 'ADD'}, location=(-200.0, -200.0))
    g.add_link('SpawnPosWorld', 'Vector', 'SpawnPosFull', 'Vector')
    g.add_link('BPosFull', 'Vector', 'SpawnPosFull', 'Vector_001')

    g.add_node('GeometryNodeSetPosition', name='PlaceSpawn', location=(-350.0, 350.0))
    g.add_link('SpawnPoints', 'Geometry', 'PlaceSpawn', 'Geometry')
    g.add_link('SpawnPosFull', 'Vector', 'PlaceSpawn', 'Position')

    g.add_node('ShaderNodeVectorMath', name='SpawnVelFull',
               properties={'operation': 'ADD'}, location=(-300.0, -500.0))
    g.add_link('VelGC', 'Vector', 'SpawnVelFull', 'Vector')
    g.add_link('BVelFull', 'Vector', 'SpawnVelFull', 'Vector_001')

    g.add_node('GeometryNodeStoreNamedAttribute', name='StoreBirthVelocity',
               properties={'data_type': 'FLOAT_VECTOR', 'domain': 'POINT'},
               input_defaults={'Name': _VELOCITY_ATTR}, location=(-200.0, 350.0))
    g.add_link('PlaceSpawn', 'Geometry', 'StoreBirthVelocity', 'Geometry')
    g.add_link('SpawnVelFull', 'Vector', 'StoreBirthVelocity', 'Value')

    g.add_node('GeometryNodeStoreNamedAttribute', name='StoreBirthAge',
               properties={'data_type': 'FLOAT', 'domain': 'POINT'},
               input_defaults={'Name': _AGE_ATTR, 'Value': 0.0}, location=(-100.0, 350.0))
    g.add_link('StoreBirthVelocity', 'Geometry', 'StoreBirthAge', 'Geometry')

    # Per-particle lifetime, floored at one frame so age normalisation holds.
    _math(g, 'LifeMin', 'SUBTRACT', (-1750.0, -2200.0))
    g.add_link(_INPUT, 'Lifetime', 'LifeMin', 'Value')
    g.add_link(_INPUT, 'Lifetime Spread', 'LifeMin', 'Value_001')
    _math(g, 'LifeMax', 'ADD', (-1750.0, -2350.0))
    g.add_link(_INPUT, 'Lifetime', 'LifeMax', 'Value')
    g.add_link(_INPUT, 'Lifetime Spread', 'LifeMax', 'Value_001')
    g.add_node('FunctionNodeRandomValue', name='LifeRand',
               properties={'data_type': 'FLOAT'}, location=(-1600.0, -2250.0))
    g.add_link('LifeMin', 'Value', 'LifeRand', 'Min_001')
    g.add_link('LifeMax', 'Value', 'LifeRand', 'Max_001')
    g.add_link('SceneTime', 'Frame', 'LifeRand', 'Seed')
    g.add_link('PIndex', 'Index', 'LifeRand', 'ID')
    _math(g, 'LifeSafe', 'MAXIMUM', (-1450.0, -2250.0), {'Value_001': 1.0})
    g.add_link('LifeRand', 'Value_001', 'LifeSafe', 'Value')
    g.add_node('GeometryNodeStoreNamedAttribute', name='StoreLife',
               properties={'data_type': 'FLOAT', 'domain': 'POINT'},
               input_defaults={'Name': _LIFE_ATTR}, location=(0.0, 350.0))
    g.add_link('StoreBirthAge', 'Geometry', 'StoreLife', 'Geometry')
    g.add_link('LifeSafe', 'Value', 'StoreLife', 'Value')

    # Billboard roll seeds: starting angle and per-frame rate, per particle.
    for tag, base, spread in (('Roll0', 'Rotation', 'Rotation Spread'),
                              ('RollRate', 'Rotation Rate', 'Rotation Rate Spread')):
        _math(g, '%sMin' % tag, 'SUBTRACT', (-1750.0, -2500.0))
        g.add_link(_INPUT, base, '%sMin' % tag, 'Value')
        g.add_link(_INPUT, spread, '%sMin' % tag, 'Value_001')
        _math(g, '%sMax' % tag, 'ADD', (-1750.0, -2650.0))
        g.add_link(_INPUT, base, '%sMax' % tag, 'Value')
        g.add_link(_INPUT, spread, '%sMax' % tag, 'Value_001')
        g.add_node('FunctionNodeRandomValue', name='%sRand' % tag,
                   properties={'data_type': 'FLOAT'}, location=(-1600.0, -2550.0))
        g.add_link('%sMin' % tag, 'Value', '%sRand' % tag, 'Min_001')
        g.add_link('%sMax' % tag, 'Value', '%sRand' % tag, 'Max_001')
        g.add_link('SceneTime', 'Frame', '%sRand' % tag, 'Seed')
        g.add_link('PIndex', 'Index', '%sRand' % tag, 'ID')

    g.add_node('GeometryNodeStoreNamedAttribute', name='StoreRoll0',
               properties={'data_type': 'FLOAT', 'domain': 'POINT'},
               input_defaults={'Name': _ROLL0_ATTR}, location=(100.0, 350.0))
    g.add_link('StoreLife', 'Geometry', 'StoreRoll0', 'Geometry')
    g.add_link('Roll0Rand', 'Value_001', 'StoreRoll0', 'Value')
    g.add_node('GeometryNodeStoreNamedAttribute', name='StoreRollRate',
               properties={'data_type': 'FLOAT', 'domain': 'POINT'},
               input_defaults={'Name': _ROLL_RATE_ATTR}, location=(200.0, 350.0))
    g.add_link('StoreRoll0', 'Geometry', 'StoreRollRate', 'Geometry')
    g.add_link('RollRateRand', 'Value_001', 'StoreRollRate', 'Value')
    return 'StoreRollRate'


def _plan_shape_disc(g):
    """DISC/cone spawn: polar position on the arc, velocity up the cone.

    Radius fraction u picks both the radius and (scaled by the cone angle)
    the velocity's tilt from the axis, so rim particles fly widest — the
    source's cone profile. ``sweep`` distributes one frame's batch evenly
    along the arc with a shared random phase.

    In: g (BRGraphBuilder, mutated).
    Out: None — terminal nodes are 'PosGC' and 'VelGC'.
    """
    X = -1750.0
    g.add_node('FunctionNodeRandomValue', name='URand',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Min_001': 0.0, 'Max_001': 1.0}, location=(X, -1200.0))
    g.add_link('SceneTime', 'Frame', 'URand', 'Seed')
    g.add_link('PIndex', 'Index', 'URand', 'ID')
    # ring: u = 1; else the draw
    _math(g, 'UInv', 'SUBTRACT', (X + 150, -1200.0), {'Value': 1.0})
    g.add_link('URand', 'Value_001', 'UInv', 'Value_001')
    _math(g, 'URingMul', 'MULTIPLY', (X + 300, -1200.0))
    g.add_link(_INPUT, 'Ring', 'URingMul', 'Value')
    g.add_link('UInv', 'Value', 'URingMul', 'Value_001')
    _math(g, 'UPick', 'ADD', (X + 450, -1200.0))
    g.add_link('URand', 'Value_001', 'UPick', 'Value')
    g.add_link('URingMul', 'Value', 'UPick', 'Value_001')
    # uniform-area: u = sqrt(u)
    _math(g, 'USqrt', 'SQRT', (X + 600, -1250.0))
    g.add_link('UPick', 'Value', 'USqrt', 'Value')
    _math(g, 'UDelta', 'SUBTRACT', (X + 750, -1250.0))
    g.add_link('USqrt', 'Value', 'UDelta', 'Value')
    g.add_link('UPick', 'Value', 'UDelta', 'Value_001')
    _math(g, 'UAMul', 'MULTIPLY', (X + 900, -1250.0))
    g.add_link(_INPUT, 'Uniform Area', 'UAMul', 'Value')
    g.add_link('UDelta', 'Value', 'UAMul', 'Value_001')
    _math(g, 'USel', 'ADD', (X + 1050, -1200.0))
    g.add_link('UPick', 'Value', 'USel', 'Value')
    g.add_link('UAMul', 'Value', 'USel', 'Value_001')
    _math(g, 'RadiusEff', 'MULTIPLY', (X + 1200, -1200.0))
    g.add_link('USel', 'Value', 'RadiusEff', 'Value')
    g.add_link(_INPUT, 'Radius', 'RadiusEff', 'Value_001')

    # Arc span; a zero span means the full circle.
    _math(g, 'Span', 'SUBTRACT', (X, -1500.0))
    g.add_link(_INPUT, 'Arc End', 'Span', 'Value')
    g.add_link(_INPUT, 'Arc Start', 'Span', 'Value_001')
    _math(g, 'SpanAbs', 'ABSOLUTE', (X + 150, -1500.0))
    g.add_link('Span', 'Value', 'SpanAbs', 'Value')
    _math(g, 'SpanIsZero', 'LESS_THAN', (X + 300, -1500.0), {'Value_001': 1e-9})
    g.add_link('SpanAbs', 'Value', 'SpanIsZero', 'Value')
    _math(g, 'SpanFix', 'MULTIPLY', (X + 450, -1500.0), {'Value_001': _TWO_PI})
    g.add_link('SpanIsZero', 'Value', 'SpanFix', 'Value')
    _math(g, 'SpanEff', 'ADD', (X + 600, -1500.0))
    g.add_link('Span', 'Value', 'SpanEff', 'Value')
    g.add_link('SpanFix', 'Value', 'SpanEff', 'Value_001')

    # Sweep azimuth: batch spread evenly with a shared random phase.
    _math(g, 'NSafe', 'MAXIMUM', (X, -1650.0), {'Value_001': 1.0})
    g.add_link('SpawnCount', 'Value', 'NSafe', 'Value')
    g.add_node('FunctionNodeRandomValue', name='PhaseRand',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Min_001': 0.0, 'Max_001': 1.0}, location=(X + 150, -1650.0))
    g.add_link('SceneTime', 'Frame', 'PhaseRand', 'Seed')
    g.add_link('SharedID', 'Integer', 'PhaseRand', 'ID')
    _math(g, 'IdxPlus', 'ADD', (X + 300, -1650.0))
    g.add_link('PIndex', 'Index', 'IdxPlus', 'Value')
    g.add_link('PhaseRand', 'Value_001', 'IdxPlus', 'Value_001')
    _math(g, 'Step', 'DIVIDE', (X + 300, -1800.0))
    g.add_link('SpanEff', 'Value', 'Step', 'Value')
    g.add_link('NSafe', 'Value', 'Step', 'Value_001')
    _math(g, 'SweepOff', 'MULTIPLY', (X + 450, -1650.0))
    g.add_link('IdxPlus', 'Value', 'SweepOff', 'Value')
    g.add_link('Step', 'Value', 'SweepOff', 'Value_001')
    _math(g, 'SweepAz', 'ADD', (X + 600, -1650.0))
    g.add_link(_INPUT, 'Arc Start', 'SweepAz', 'Value')
    g.add_link('SweepOff', 'Value', 'SweepAz', 'Value_001')

    # Random azimuth in the arc.
    g.add_node('FunctionNodeRandomValue', name='AzRand',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Min_001': 0.0, 'Max_001': 1.0}, location=(X + 150, -1950.0))
    g.add_link('SceneTime', 'Frame', 'AzRand', 'Seed')
    g.add_link('PIndex', 'Index', 'AzRand', 'ID')
    _math(g, 'RandAzMul', 'MULTIPLY', (X + 300, -1950.0))
    g.add_link('AzRand', 'Value_001', 'RandAzMul', 'Value')
    g.add_link('SpanEff', 'Value', 'RandAzMul', 'Value_001')
    _math(g, 'RandAz', 'ADD', (X + 450, -1950.0))
    g.add_link(_INPUT, 'Arc Start', 'RandAz', 'Value')
    g.add_link('RandAzMul', 'Value', 'RandAz', 'Value_001')

    # Pick sweep or random.
    _math(g, 'AzDelta', 'SUBTRACT', (X + 750, -1800.0))
    g.add_link('SweepAz', 'Value', 'AzDelta', 'Value')
    g.add_link('RandAz', 'Value', 'AzDelta', 'Value_001')
    _math(g, 'AzSweepMul', 'MULTIPLY', (X + 900, -1800.0))
    g.add_link(_INPUT, 'Sweep', 'AzSweepMul', 'Value')
    g.add_link('AzDelta', 'Value', 'AzSweepMul', 'Value_001')
    _math(g, 'Azim', 'ADD', (X + 1050, -1800.0))
    g.add_link('RandAz', 'Value', 'Azim', 'Value')
    g.add_link('AzSweepMul', 'Value', 'Azim', 'Value_001')

    _math(g, 'CosAz', 'COSINE', (X + 1200, -1750.0))
    g.add_link('Azim', 'Value', 'CosAz', 'Value')
    _math(g, 'SinAz', 'SINE', (X + 1200, -1900.0))
    g.add_link('Azim', 'Value', 'SinAz', 'Value')

    _math(g, 'PosX', 'MULTIPLY', (X + 1350, -1750.0))
    g.add_link('RadiusEff', 'Value', 'PosX', 'Value')
    g.add_link('CosAz', 'Value', 'PosX', 'Value_001')
    _math(g, 'PosY', 'MULTIPLY', (X + 1350, -1900.0))
    g.add_link('RadiusEff', 'Value', 'PosY', 'Value')
    g.add_link('SinAz', 'Value', 'PosY', 'Value_001')
    g.add_node('ShaderNodeCombineXYZ', name='PosGC', location=(X + 1500, -1800.0))
    g.add_link('PosX', 'Value', 'PosGC', 'X')
    g.add_link('PosY', 'Value', 'PosGC', 'Y')

    # Velocity: tilt from the axis grows with the radius fraction.
    _math(g, 'Elev', 'MULTIPLY', (X + 1200, -2050.0))
    g.add_link('USel', 'Value', 'Elev', 'Value')
    g.add_link(_INPUT, 'Cone Angle', 'Elev', 'Value_001')
    _math(g, 'SinE', 'SINE', (X + 1350, -2050.0))
    g.add_link('Elev', 'Value', 'SinE', 'Value')
    _math(g, 'CosE', 'COSINE', (X + 1350, -2200.0))
    g.add_link('Elev', 'Value', 'CosE', 'Value')

    g.add_node('ShaderNodeVectorMath', name='ShapeSpeed',
               properties={'operation': 'LENGTH'}, location=(X, -2050.0))
    g.add_link(_INPUT, 'Shape Velocity', 'ShapeSpeed', 'Vector')
    # uniform-area discs also scale speed by the radius fraction
    _math(g, 'SpdUD', 'SUBTRACT', (X + 150, -2100.0), {'Value_001': 1.0})
    g.add_link('USel', 'Value', 'SpdUD', 'Value')
    _math(g, 'SpdUAM', 'MULTIPLY', (X + 300, -2100.0))
    g.add_link(_INPUT, 'Uniform Area', 'SpdUAM', 'Value')
    g.add_link('SpdUD', 'Value', 'SpdUAM', 'Value_001')
    _math(g, 'SpdF', 'ADD', (X + 450, -2100.0), {'Value': 1.0})
    g.add_link('SpdUAM', 'Value', 'SpdF', 'Value_001')
    _math(g, 'SpeedEff', 'MULTIPLY', (X + 600, -2100.0))
    g.add_link('ShapeSpeed', 'Value', 'SpeedEff', 'Value')
    g.add_link('SpdF', 'Value', 'SpeedEff', 'Value_001')

    _math(g, 'VxA', 'MULTIPLY', (X + 1500, -2050.0))
    g.add_link('SinE', 'Value', 'VxA', 'Value')
    g.add_link('CosAz', 'Value', 'VxA', 'Value_001')
    _math(g, 'Vx', 'MULTIPLY', (X + 1650, -2050.0))
    g.add_link('VxA', 'Value', 'Vx', 'Value')
    g.add_link('SpeedEff', 'Value', 'Vx', 'Value_001')
    _math(g, 'VyA', 'MULTIPLY', (X + 1500, -2200.0))
    g.add_link('SinE', 'Value', 'VyA', 'Value')
    g.add_link('SinAz', 'Value', 'VyA', 'Value_001')
    _math(g, 'Vy', 'MULTIPLY', (X + 1650, -2200.0))
    g.add_link('VyA', 'Value', 'Vy', 'Value')
    g.add_link('SpeedEff', 'Value', 'Vy', 'Value_001')
    _math(g, 'Vz', 'MULTIPLY', (X + 1650, -2350.0))
    g.add_link('CosE', 'Value', 'Vz', 'Value')
    g.add_link('SpeedEff', 'Value', 'Vz', 'Value_001')
    g.add_node('ShaderNodeCombineXYZ', name='VelGC', location=(X + 1800, -2200.0))
    g.add_link('Vx', 'Value', 'VelGC', 'X')
    g.add_link('Vy', 'Value', 'VelGC', 'Y')
    g.add_link('Vz', 'Value', 'VelGC', 'Z')


def _plan_shape_box(g):
    """BOX spawn: fill the extents; a negative extent emits on its face.

    In: g (BRGraphBuilder, mutated).
    Out: None — terminal nodes are 'PosGC' and 'VelGC'.
    """
    X = -1750.0
    g.add_node('FunctionNodeRandomValue', name='BoxRand',
               properties={'data_type': 'FLOAT_VECTOR'},
               input_defaults={'Min': (0.0, 0.0, 0.0), 'Max': (1.0, 1.0, 1.0)},
               location=(X, -1200.0))
    g.add_link('SceneTime', 'Frame', 'BoxRand', 'Seed')
    g.add_link('PIndex', 'Index', 'BoxRand', 'ID')
    g.add_node('ShaderNodeSeparateXYZ', name='BoxRandSep', location=(X + 150, -1200.0))
    g.add_link('BoxRand', 'Value', 'BoxRandSep', 'Vector')
    g.add_node('ShaderNodeSeparateXYZ', name='ExtSep', location=(X, -1400.0))
    g.add_link(_INPUT, 'Box Extents', 'ExtSep', 'Vector')

    for axis in ('X', 'Y', 'Z'):
        _math(g, 'Face%s' % axis, 'LESS_THAN', (X + 300, -1200.0), {'Value_001': 0.0})
        g.add_link('ExtSep', axis, 'Face%s' % axis, 'Value')
        _math(g, 'U%sInv' % axis, 'SUBTRACT', (X + 450, -1200.0), {'Value': 1.0})
        g.add_link('BoxRandSep', axis, 'U%sInv' % axis, 'Value_001')
        _math(g, 'U%sFace' % axis, 'MULTIPLY', (X + 600, -1200.0))
        g.add_link('Face%s' % axis, 'Value', 'U%sFace' % axis, 'Value')
        g.add_link('U%sInv' % axis, 'Value', 'U%sFace' % axis, 'Value_001')
        _math(g, 'U%sSel' % axis, 'ADD', (X + 750, -1200.0))
        g.add_link('BoxRandSep', axis, 'U%sSel' % axis, 'Value')
        g.add_link('U%sFace' % axis, 'Value', 'U%sSel' % axis, 'Value_001')
        _math(g, 'P%s' % axis, 'MULTIPLY', (X + 900, -1200.0))
        g.add_link('U%sSel' % axis, 'Value', 'P%s' % axis, 'Value')
        g.add_link('ExtSep', axis, 'P%s' % axis, 'Value_001')

    g.add_node('ShaderNodeCombineXYZ', name='PosGC', location=(X + 1050, -1300.0))
    for axis in ('X', 'Y', 'Z'):
        g.add_link('P%s' % axis, 'Value', 'PosGC', axis)

    g.add_node('ShaderNodeVectorMath', name='ShapeSpeed',
               properties={'operation': 'LENGTH'}, location=(X, -1700.0))
    g.add_link(_INPUT, 'Shape Velocity', 'ShapeSpeed', 'Vector')
    _math(g, 'SignZ', 'SIGN', (X + 150, -1700.0))
    g.add_link('ExtSep', 'Z', 'SignZ', 'Value')
    _math(g, 'VzBox', 'MULTIPLY', (X + 300, -1700.0))
    g.add_link('ShapeSpeed', 'Value', 'VzBox', 'Value')
    g.add_link('SignZ', 'Value', 'VzBox', 'Value_001')
    g.add_node('ShaderNodeCombineXYZ', name='VelGC', location=(X + 450, -1700.0))
    g.add_link('VzBox', 'Value', 'VelGC', 'Z')


def _plan_shape_sphere(g):
    """SPHERE spawn: random direction up to the polar cap, radial motion.

    In: g (BRGraphBuilder, mutated).
    Out: None — terminal nodes are 'PosGC' and 'VelGC'.
    """
    X = -1750.0
    _math(g, 'PolZero', 'LESS_THAN', (X, -1200.0), {'Value_001': 1e-9})
    g.add_link(_INPUT, 'Polar Max', 'PolZero', 'Value')
    _math(g, 'PolFix', 'MULTIPLY', (X + 150, -1200.0), {'Value_001': _PI})
    g.add_link('PolZero', 'Value', 'PolFix', 'Value')
    _math(g, 'PolarEff', 'ADD', (X + 300, -1200.0))
    g.add_link(_INPUT, 'Polar Max', 'PolarEff', 'Value')
    g.add_link('PolFix', 'Value', 'PolarEff', 'Value_001')

    g.add_node('FunctionNodeRandomValue', name='ERand',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Min_001': 0.0, 'Max_001': 1.0}, location=(X, -1400.0))
    g.add_link('SceneTime', 'Frame', 'ERand', 'Seed')
    g.add_link('PIndex', 'Index', 'ERand', 'ID')
    _math(g, 'Elev', 'MULTIPLY', (X + 450, -1400.0))
    g.add_link('ERand', 'Value_001', 'Elev', 'Value')
    g.add_link('PolarEff', 'Value', 'Elev', 'Value_001')
    g.add_node('FunctionNodeRandomValue', name='ARand',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Min_001': 0.0, 'Max_001': _TWO_PI},
               location=(X, -1600.0))
    g.add_link('SceneTime', 'Frame', 'ARand', 'Seed')
    g.add_link('PIndex', 'Index', 'ARand', 'ID')

    _math(g, 'SinE', 'SINE', (X + 600, -1400.0))
    g.add_link('Elev', 'Value', 'SinE', 'Value')
    _math(g, 'CosE', 'COSINE', (X + 600, -1550.0))
    g.add_link('Elev', 'Value', 'CosE', 'Value')
    _math(g, 'CosA', 'COSINE', (X + 600, -1700.0))
    g.add_link('ARand', 'Value_001', 'CosA', 'Value')
    _math(g, 'SinA', 'SINE', (X + 600, -1850.0))
    g.add_link('ARand', 'Value_001', 'SinA', 'Value')

    _math(g, 'Dx', 'MULTIPLY', (X + 750, -1450.0))
    g.add_link('SinE', 'Value', 'Dx', 'Value')
    g.add_link('CosA', 'Value', 'Dx', 'Value_001')
    _math(g, 'Dy', 'MULTIPLY', (X + 750, -1600.0))
    g.add_link('SinE', 'Value', 'Dy', 'Value')
    g.add_link('SinA', 'Value', 'Dy', 'Value_001')
    g.add_node('ShaderNodeCombineXYZ', name='DirGC', location=(X + 900, -1500.0))
    g.add_link('Dx', 'Value', 'DirGC', 'X')
    g.add_link('Dy', 'Value', 'DirGC', 'Y')
    g.add_link('CosE', 'Value', 'DirGC', 'Z')

    g.add_node('FunctionNodeRandomValue', name='RRand',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Min_001': 0.0, 'Max_001': 1.0}, location=(X, -2000.0))
    g.add_link('SceneTime', 'Frame', 'RRand', 'Seed')
    g.add_link('PIndex', 'Index', 'RRand', 'ID')
    _math(g, 'RInv', 'SUBTRACT', (X + 150, -2000.0), {'Value': 1.0})
    g.add_link('RRand', 'Value_001', 'RInv', 'Value_001')
    _math(g, 'RRingMul', 'MULTIPLY', (X + 300, -2000.0))
    g.add_link(_INPUT, 'Ring', 'RRingMul', 'Value')
    g.add_link('RInv', 'Value', 'RRingMul', 'Value_001')
    _math(g, 'RPick', 'ADD', (X + 450, -2000.0))
    g.add_link('RRand', 'Value_001', 'RPick', 'Value')
    g.add_link('RRingMul', 'Value', 'RPick', 'Value_001')
    _math(g, 'REff', 'MULTIPLY', (X + 600, -2000.0))
    g.add_link('RPick', 'Value', 'REff', 'Value')
    g.add_link(_INPUT, 'Radius', 'REff', 'Value_001')

    g.add_node('ShaderNodeVectorMath', name='PosGC',
               properties={'operation': 'SCALE'}, location=(X + 1050, -1500.0))
    g.add_link('DirGC', 'Vector', 'PosGC', 'Vector')
    g.add_link('REff', 'Value', 'PosGC', 'Scale')
    g.add_node('ShaderNodeVectorMath', name='VelGC',
               properties={'operation': 'SCALE'}, location=(X + 1050, -1700.0))
    g.add_link('DirGC', 'Vector', 'VelGC', 'Vector')
    g.add_link(_INPUT, 'Radial Speed', 'VelGC', 'Scale')


def _plan_motion(g, spawned):
    """Integrate the population: join newborns, apply forces, retire the old.

    In: g (BRGraphBuilder, mutated); spawned (str, node emitting this
        frame's placed newborns).
    Out: None — the surviving points feed the simulation output.
    """
    g.add_node('GeometryNodeJoinGeometry', name='AddSpawned', location=(-450.0, 0.0))
    g.add_link(_SIM_IN, 'Item_0', 'AddSpawned', 'Geometry')
    g.add_link(spawned, 'Geometry', 'AddSpawned', 'Geometry')

    g.add_node('GeometryNodeInputNamedAttribute', name='ReadVelocity',
               properties={'data_type': 'FLOAT_VECTOR'},
               input_defaults={'Name': _VELOCITY_ATTR}, location=(-450.0, -300.0))
    g.add_node('GeometryNodeInputNamedAttribute', name='ReadAge',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Name': _AGE_ATTR}, location=(-450.0, -450.0))
    g.add_node('GeometryNodeInputNamedAttribute', name='ReadLife',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Name': _LIFE_ATTR}, location=(-450.0, -600.0))

    # velocity' = velocity x (1 - drag) + gravity
    _math(g, 'DragFactor', 'SUBTRACT', (-300.0, -300.0), {'Value': 1.0})
    g.add_link(_INPUT, 'Drag', 'DragFactor', 'Value_001')
    g.add_node('ShaderNodeVectorMath', name='Damped',
               properties={'operation': 'SCALE'}, location=(-200.0, -300.0))
    g.add_link('ReadVelocity', 'Attribute', 'Damped', 'Vector')
    g.add_link('DragFactor', 'Value', 'Damped', 'Scale')
    g.add_node('ShaderNodeVectorMath', name='NextVelocity',
               properties={'operation': 'ADD'}, location=(-100.0, -300.0))
    g.add_link('Damped', 'Vector', 'NextVelocity', 'Vector')
    g.add_link(_INPUT, 'Gravity', 'NextVelocity', 'Vector_001')

    g.add_node('GeometryNodeStoreNamedAttribute', name='StoreVelocity',
               properties={'data_type': 'FLOAT_VECTOR', 'domain': 'POINT'},
               input_defaults={'Name': _VELOCITY_ATTR}, location=(-300.0, 0.0))
    g.add_link('AddSpawned', 'Geometry', 'StoreVelocity', 'Geometry')
    g.add_link('NextVelocity', 'Vector', 'StoreVelocity', 'Value')

    g.add_node('GeometryNodeSetPosition', name='Advance', location=(-200.0, 0.0))
    g.add_link('StoreVelocity', 'Geometry', 'Advance', 'Geometry')
    g.add_link('NextVelocity', 'Vector', 'Advance', 'Offset')

    _math(g, 'NextAge', 'ADD', (-300.0, -450.0), {'Value_001': 1.0})
    g.add_link('ReadAge', 'Attribute', 'NextAge', 'Value')
    g.add_node('GeometryNodeStoreNamedAttribute', name='StoreAge',
               properties={'data_type': 'FLOAT', 'domain': 'POINT'},
               input_defaults={'Name': _AGE_ATTR}, location=(-100.0, 0.0))
    g.add_link('Advance', 'Geometry', 'StoreAge', 'Geometry')
    g.add_link('NextAge', 'Value', 'StoreAge', 'Value')

    _math(g, 'Expired', 'GREATER_THAN', (-100.0, -450.0))
    g.add_link('ReadAge', 'Attribute', 'Expired', 'Value')
    g.add_link('ReadLife', 'Attribute', 'Expired', 'Value_001')
    g.add_node('GeometryNodeDeleteGeometry', name='Retire',
               properties={'domain': 'POINT', 'mode': 'ALL'}, location=(0.0, 0.0))
    g.add_link('StoreAge', 'Geometry', 'Retire', 'Geometry')
    g.add_link('Expired', 'Value', 'Retire', 'Selection')

    g.add_link('Retire', 'Geometry', _SIM_OUT, 'Item_0')


def _plan_render_stage(g):
    """Surviving particles → camera-facing, rolled, tinted, sized quads.

    In: g (BRGraphBuilder, mutated).
    Out: str — node whose Geometry output is the final geometry.
    """
    g.add_node('GeometryNodeInputNamedAttribute', name='RReadAge',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Name': _AGE_ATTR}, location=(700.0, -300.0))
    g.add_node('GeometryNodeInputNamedAttribute', name='RReadLife',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Name': _LIFE_ATTR}, location=(700.0, -450.0))
    _math(g, 'NormalizedAge', 'DIVIDE', (850.0, -350.0))
    g.add_link('RReadAge', 'Attribute', 'NormalizedAge', 'Value')
    g.add_link('RReadLife', 'Attribute', 'NormalizedAge', 'Value_001')

    g.add_node('ShaderNodeValToRGB', name=_RAMP_NODE, location=(850.0, -600.0))
    g.add_link('NormalizedAge', 'Value', _RAMP_NODE, 'Fac')
    g.add_node('ShaderNodeFloatCurve', name=_CURVE_NODE, location=(850.0, -900.0))
    g.add_link('NormalizedAge', 'Value', _CURVE_NODE, 'Value')

    g.add_node('GeometryNodeStoreNamedAttribute', name='StoreColor',
               properties={'data_type': 'FLOAT_COLOR', 'domain': 'POINT'},
               input_defaults={'Name': _COLOR_ATTR}, location=(900.0, 0.0))
    g.add_link(_SIM_OUT, 'Item_0', 'StoreColor', 'Geometry')
    g.add_link(_RAMP_NODE, 'Color', 'StoreColor', 'Value')

    # Billboard roll: angle = roll0 + rate x age + accel x age^2 / 2.
    g.add_node('GeometryNodeInputNamedAttribute', name='ReadRoll0',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Name': _ROLL0_ATTR}, location=(700.0, -1200.0))
    g.add_node('GeometryNodeInputNamedAttribute', name='ReadRollRate',
               properties={'data_type': 'FLOAT'},
               input_defaults={'Name': _ROLL_RATE_ATTR}, location=(700.0, -1350.0))
    _math(g, 'RollLin', 'MULTIPLY', (850.0, -1300.0))
    g.add_link('ReadRollRate', 'Attribute', 'RollLin', 'Value')
    g.add_link('RReadAge', 'Attribute', 'RollLin', 'Value_001')
    _math(g, 'AgeSq', 'MULTIPLY', (850.0, -1450.0))
    g.add_link('RReadAge', 'Attribute', 'AgeSq', 'Value')
    g.add_link('RReadAge', 'Attribute', 'AgeSq', 'Value_001')
    _math(g, 'AccelTermA', 'MULTIPLY', (1000.0, -1450.0))
    g.add_link('AgeSq', 'Value', 'AccelTermA', 'Value')
    g.add_link(_INPUT, 'Rotation Accel', 'AccelTermA', 'Value_001')
    _math(g, 'AccelTerm', 'MULTIPLY', (1150.0, -1450.0), {'Value_001': 0.5})
    g.add_link('AccelTermA', 'Value', 'AccelTerm', 'Value')
    _math(g, 'RollSum1', 'ADD', (1000.0, -1300.0))
    g.add_link('ReadRoll0', 'Attribute', 'RollSum1', 'Value')
    g.add_link('RollLin', 'Value', 'RollSum1', 'Value_001')
    _math(g, 'RollTotal', 'ADD', (1150.0, -1300.0))
    g.add_link('RollSum1', 'Value', 'RollTotal', 'Value')
    g.add_link('AccelTerm', 'Value', 'RollTotal', 'Value_001')

    g.add_node('ShaderNodeCombineXYZ', name='RollEuler', location=(1250.0, -1300.0))
    g.add_link('RollTotal', 'Value', 'RollEuler', 'Z')
    g.add_node('FunctionNodeEulerToRotation', name='RollRot', location=(1350.0, -1300.0))
    g.add_link('RollEuler', 'Vector', 'RollRot', 'Euler')
    # Camera orientation first, then the roll about the camera's own axis.
    g.add_node('FunctionNodeRotateRotation', name='FaceCamera',
               properties={'rotation_space': 'LOCAL'}, location=(1450.0, -1200.0))
    g.add_link('CameraInfo', 'Rotation', 'FaceCamera', 'Rotation')
    g.add_link('RollRot', 'Rotation', 'FaceCamera', 'Rotate By')

    quad = _plan_cross_quad(g)

    g.add_node('GeometryNodeInstanceOnPoints', name='Billboards', location=(1100.0, 0.0))
    g.add_link('StoreColor', 'Geometry', 'Billboards', 'Points')
    g.add_link(quad, 'Geometry', 'Billboards', 'Instance')
    g.add_link('FaceCamera', 'Rotation', 'Billboards', 'Rotation')
    g.add_link(_CURVE_NODE, 'Value', 'Billboards', 'Scale')

    # Realize before shading: the per-particle colour rides the instance
    # domain, and a shader reads it reliably only as a real point attribute.
    g.add_node('GeometryNodeRealizeInstances', name='Realize', location=(1250.0, 0.0))
    g.add_link('Billboards', 'Instances', 'Realize', 'Geometry')
    g.add_node('GeometryNodeSetMaterial', name=_MATERIAL_NODE, location=(1400.0, 0.0))
    g.add_link('Realize', 'Geometry', _MATERIAL_NODE, 'Geometry')
    return _MATERIAL_NODE


def _plan_cross_quad(g):
    """Two unit quads at right angles — reads from any camera fallback angle.

    With a camera bound the pair tracks the view (one face-on, one edge-on);
    with none, the cross still reads in a still render.

    In: g (BRGraphBuilder, mutated).
    Out: str — name of the node whose Geometry output is the crossed pair.
    """
    # The source draws billboards corner-to-corner at ±scale along the
    # camera diagonals — two units per side — so the unit here is 2.
    g.add_node('GeometryNodeMeshGrid', name='Quad',
               input_defaults={'Size X': 2.0, 'Size Y': 2.0,
                               'Vertices X': 2, 'Vertices Y': 2},
               location=(800.0, 400.0))
    # The grid's UVs exist only as a socket until stored; without a real UV
    # layer the sprite never maps and every fragment samples one corner texel.
    g.add_node('GeometryNodeStoreNamedAttribute', name='QuadUV',
               properties={'data_type': 'FLOAT2', 'domain': 'CORNER'},
               input_defaults={'Name': 'UVMap'}, location=(875.0, 400.0))
    g.add_link('Quad', 'Mesh', 'QuadUV', 'Geometry')
    g.add_link('Quad', 'UV Map', 'QuadUV', 'Value')
    for name, rotation in (('QuadFront', (0.0, 0.0, 0.0)),
                           ('QuadSide', (0.0, math.pi / 2.0, 0.0))):
        g.add_node('GeometryNodeTransform', name=name,
                   input_defaults={'Rotation': rotation}, location=(950.0, 400.0))
        g.add_link('QuadUV', 'Geometry', name, 'Geometry')
    g.add_node('GeometryNodeJoinGeometry', name='CrossQuad', location=(1050.0, 400.0))
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

    Sizes are absolute quad widths, already in metres like every other IR
    length, so they carry straight over into Blender units. The clip box is
    widened to the curve's own range — Blender clamps curve values to it, and
    a particle can outgrow the default 0-1. A constant size (empty IR list)
    becomes a flat two-point curve.

    In: em (IRParticleEmitter).
    Out: BRFloatCurve.
    """
    points = [BRCurvePoint(x=position, y=key.value)
              for position, key in _lay_out(_downsample(em.size_over_life,
                                                        _MAX_RAMP_STOPS))]
    if len(points) < 2:
        # A curve needs two points to span the age axis: either the size
        # never changes (no IR keys) or every key collapsed onto one age.
        size = points[0].y if points else em.birth.size.base
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
    """Build the emitter's material for its blend mode.

    Particles are unlit in the source engine, so all four variants build on
    colour = texture x per-particle tint and alpha = texAlpha x tintAlpha:

    - ``ALPHA``: Emission mixed against Transparent by alpha.
    - ``ADD``: Transparent (the background passes whole) plus Emission
      scaled by alpha — the standard additive recipe.
    - ``MULTIPLY``: a tinted Transparent BSDF alone; a transparent
      surface's colour multiplies whatever is behind it.
    - ``SUBTRACT``: approximated as multiplication by the inverted colour
      (darkening), the closest a surface shader gets to GX subtract.

    In: em (IRParticleEmitter); name (str, material name);
        images (list[BRImage], system-wide, indexed by flip-book frame).
    Out: BRMaterial.
    """
    g = BRGraphBuilder()
    output = g.add_node('ShaderNodeOutputMaterial', name='Output',
                        location=(500.0, 0.0))

    # Each particle's own colour rides the realized geometry as a point
    # attribute — the emitter's ColorRamp writes it per particle.
    tint = g.add_node('ShaderNodeAttribute', name='ParticleColor',
                      properties={'attribute_type': 'GEOMETRY',
                                  'attribute_name': _COLOR_ATTR},
                      location=(-400.0, -300.0))

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

    blend = em.render.blend_mode
    if blend == 'ADD':
        _plan_additive_shader(g, color_ref, alpha_ref, output)
    elif blend in ('MULTIPLY', 'SUBTRACT'):
        _plan_filter_shader(g, color_ref, alpha_ref, output,
                            invert=(blend == 'SUBTRACT'))
    else:
        _plan_alpha_shader(g, color_ref, alpha_ref, output)

    return BRMaterial(
        name=name,
        node_graph=g.finalize(),
        blend_method='BLEND',
        dedup_key=('particle', name),
    )


def _plan_alpha_shader(g, color_ref, alpha_ref, output):
    """Standard alpha blending: Emission over Transparent by alpha."""
    emission = g.add_node('ShaderNodeEmission', name='ParticleEmission',
                          location=(0.0, 0.0))
    transparent = g.add_node('ShaderNodeBsdfTransparent', name='ParticleTransparent',
                             location=(0.0, 180.0))
    mix = g.add_node('ShaderNodeMixShader', name='ParticleAlphaMix',
                     location=(250.0, 0.0))
    g.add_link(color_ref[0], color_ref[1], emission, 0)
    g.add_link(alpha_ref[0], alpha_ref[1], mix, 0)
    g.add_link(transparent, 0, mix, 1)
    g.add_link(emission, 0, mix, 2)
    g.add_link(mix, 0, output, 0)


def _plan_additive_shader(g, color_ref, alpha_ref, output):
    """Additive: the background passes whole, the particle adds on top."""
    emission = g.add_node('ShaderNodeEmission', name='ParticleEmission',
                          location=(0.0, 0.0))
    transparent = g.add_node('ShaderNodeBsdfTransparent', name='ParticleTransparent',
                             location=(0.0, 180.0))
    add = g.add_node('ShaderNodeAddShader', name='ParticleAdd',
                     location=(250.0, 0.0))
    # Emission strength carries the alpha so the sprite fades additively.
    g.add_link(color_ref[0], color_ref[1], emission, 0)
    g.add_link(alpha_ref[0], alpha_ref[1], emission, 1)
    g.add_link(transparent, 0, add, 0)
    g.add_link(emission, 0, add, 1)
    g.add_link(add, 0, output, 0)


def _plan_filter_shader(g, color_ref, alpha_ref, output, invert):
    """Multiplicative (or subtract-approximating) filter over the background.

    A Transparent BSDF's colour multiplies what lies behind it. Alpha
    lerps the filter toward white (no effect) so faded particles vanish.
    """
    tinted = g.add_node('ShaderNodeMixRGB', name='ParticleFilterColor',
                        properties={'blend_type': 'MIX'},
                        input_defaults={1: (1.0, 1.0, 1.0, 1.0)},
                        location=(-20.0, 60.0))
    g.add_link(alpha_ref[0], alpha_ref[1], tinted, 0)
    if invert:
        inverted = g.add_node('ShaderNodeInvert', name='ParticleInvert',
                              input_defaults={0: 1.0}, location=(-180.0, 60.0))
        g.add_link(color_ref[0], color_ref[1], inverted, 1)
        g.add_link(inverted, 0, tinted, 2)
    else:
        g.add_link(color_ref[0], color_ref[1], tinted, 2)
    transparent = g.add_node('ShaderNodeBsdfTransparent', name='ParticleTransparent',
                             location=(150.0, 60.0))
    g.add_link(tinted, 0, transparent, 0)
    g.add_link(transparent, 0, output, 0)


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
