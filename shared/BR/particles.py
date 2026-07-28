"""Blender-specialised particle types.

One BRParticleEmitter per IR emitter. Every value here is already a Blender
value: Z-up vectors, linear RGB, world-unit sizes, node-group interface
socket types, ColorRamp stops and Float-Curve points laid out for direct
assignment. The build phase creates one mesh object per emitter carrying a
Geometry Nodes modifier whose group holds the emitter's parameters as
interface inputs plus the over-life ramp/curve as editable nodes.

List-valued content that has no native Blender slot (flip-book frame
schedule, sub-emitter triggers, emission bursts) rides as flat custom-prop
arrays in ``BRParticleEmitter.custom_props``.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .materials import BRImage, BRMaterial, BRNode, BRLink


@dataclass
class BRInterfaceSocket:
    """One node-group interface socket plus the value the modifier carries.

    ``socket_type`` is the Blender socket bl_idname ('NodeSocketFloat',
    'NodeSocketInt', 'NodeSocketVector', 'NodeSocketBool', 'NodeSocketColor',
    'NodeSocketGeometry'). ``value`` is both the interface default and the
    value build writes onto the modifier — the group is per-emitter, so
    there is only ever one value per socket.
    """
    name: str
    socket_type: str
    value: object = None
    subtype: str | None = None        # e.g. 'FACTOR', 'TRANSLATION', 'ANGLE'
    min_value: float | None = None
    max_value: float | None = None
    description: str = ''


@dataclass
class BRColorRampStop:
    """One ColorRamp element: position in [0, 1] plus linear RGBA."""
    position: float = 0.0
    color: tuple = (1.0, 1.0, 1.0, 1.0)


@dataclass
class BRColorRamp:
    """A ``ShaderNodeValToRGB`` payload — stops are strictly ordered and
    already trimmed to Blender's 32-element ceiling."""
    stops: list[BRColorRampStop] = field(default_factory=list)
    interpolation: str = 'LINEAR'
    color_mode: str = 'RGB'


@dataclass
class BRCurvePoint:
    """One Float-Curve point."""
    x: float = 0.0
    y: float = 0.0


@dataclass
class BRFloatCurve:
    """A ``ShaderNodeFloatCurve`` payload.

    ``clip_max_y`` is widened by the plan phase to fit the curve's own
    range — Blender clamps curve values to the clip box, and particle
    sizes routinely exceed the default 0-1.
    """
    points: list[BRCurvePoint] = field(default_factory=list)
    use_clip: bool = True
    clip_min_y: float = 0.0
    clip_max_y: float = 1.0


@dataclass
class BRParticleNodeGroup:
    """Spec for one emitter's GeometryNodeTree.

    ``nodes``/``links`` reuse the shader-graph BR types (both are just
    bl_idname + socket-keyed data). Links address sockets by identifier
    where one exists and by socket *name* on the group input/output nodes,
    whose identifiers are assigned by Blender at interface-creation time.

    ``simulation_zones`` names the (input, output) node pairs build must
    pair before linking — a zone's geometry sockets only exist once paired.
    """
    name: str
    inputs: list[BRInterfaceSocket] = field(default_factory=list)
    outputs: list[BRInterfaceSocket] = field(default_factory=list)
    nodes: list[BRNode] = field(default_factory=list)
    links: list[BRLink] = field(default_factory=list)
    color_ramps: dict = field(default_factory=dict)    # node name → BRColorRamp
    float_curves: dict = field(default_factory=dict)   # node name → BRFloatCurve
    simulation_zones: list = field(default_factory=list)  # [(input name, output name)]


@dataclass
class BRParticleAttach:
    """A bone-parented Empty marking where a firing bone sits.

    Emitters spawn at these rather than being parented to a bone: the game
    creates a generator instance per firing event and attaches it to the
    firing bone, so one emitter can be alive on several bones at once, and
    particles already spawned must keep their own world path instead of
    riding along with the bone.
    """
    name: str
    bone_name: str


@dataclass
class BRParticleEmitDriver:
    """Ties an emitter's preview to the spawn events that actually fire it.

    Build drives the group's ``Emit`` input from the firing bone's
    ``particle_emit`` lanes: the emitter runs only while one of them holds
    its index, so a clip shows what the game would show rather than every
    emitter at once. The fcurves stay the one source of truth — this only
    reads them.
    """
    bone_name: str
    lane_count: int
    emitter_index: int


@dataclass
class BRParticleEmitter:
    """One emitter: a single-vertex mesh object driven by a geometry-node group."""
    name: str                                          # object name
    node_group: BRParticleNodeGroup | None = None
    material: BRMaterial | None = None
    custom_props: dict = field(default_factory=dict)
    # Name of the BRParticleAttach this emitter spawns from; None spawns at
    # the system root (emitters no clip fires — sub-emitters, mostly).
    attach_name: str | None = None
    emit_driver: BRParticleEmitDriver | None = None


@dataclass
class BRParticleSystem:
    """All emitters and textures of one model.

    ``root_name`` is the Empty every emitter object is parented to; build
    parents that Empty to the armature so the whole system follows the
    model. ``images`` holds every particle texture (build creates them all,
    deduped by ``BRImage.cache_key``, so textures no emitter currently
    samples still survive a round-trip).
    """
    root_name: str = ''
    emitters: list[BRParticleEmitter] = field(default_factory=list)
    images: list[BRImage] = field(default_factory=list)
    attaches: list[BRParticleAttach] = field(default_factory=list)
