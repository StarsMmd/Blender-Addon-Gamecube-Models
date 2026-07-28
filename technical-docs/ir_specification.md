# Intermediate Representation (IR) Specification

The IR is the output of Phase 4 (Scene Description) and the input to Phase 5 (Plan). It is a pure-Python dataclass hierarchy with no dependencies on `bpy` or the Node system.

The downstream Blender-specialised counterpart produced by the Plan phase is the **BR** (Blender Representation). See [br_specification.md](br_specification.md) for that spec.

> **Note:** Shiny variant data bypasses the IR entirely. Raw shiny parameters are extracted in Phase 1 (extract) and passed directly to Phase 7 (post_process), which applies them to Blender materials after the main build is complete.

**Design principles:**
- All types are `@dataclass` from the standard library
- All categorical values use Python `enum.Enum`
- No mutable shared state — each IR instance is a self-contained snapshot
- Materials store abstract rendering parameters, not target-specific shader graphs (target-specific shader-graph shape lives in BR)
- Animation keyframes are fully decoded (frame/value/interpolation/handles) — not compressed bytes, not target-baked values
- Image pixels are raw u8 bytes — float conversion happens in the build phase
- Platform-agnostic: no source-format quirks (GameCube) or target-format quirks (Blender) — Phase 4 strips the former, Phase 5 translates the latter

---

## Conventions & Coordinate Spaces

The IR uses standard, widely-adopted conventions so that any build phase can consume it without needing to know about the original game format.

| Property | Convention | Notes |
|---|---|---|
| **Coordinate system** | Y-up, right-handed | GameCube uses Y-up natively; the π/2 X-rotation for Blender's Z-up is applied in Phase 5 (Plan) at the armature level via `BRArmature.matrix_basis` |
| **Rotation** | Euler XYZ, radians | Stored as `(rx, ry, rz)` tuples |
| **Matrices** | 4×4, row-major | Stored as `list[list[float]]` (4 rows of 4 floats) |
| **UV origin** | Bottom-left (OpenGL convention) | Phase 4 flips V from GameCube's top-left origin: `v = 1 - scale_v - v` |
| **UV animation** | Bottom-left, V-flipped in Phase 4 | Animated `translation_v` keyframes are corrected using the static or animated `scale_v` value at each keyframe's frame |
| **Color space** | sRGB [0, 1] | Diffuse/ambient/specular/vertex colors are normalized from u8 [0, 255] to float [0, 1] but remain in sRGB space. Linearization for Blender happens in Phase 5 (Plan) when constructing BR material/light colors |
| **Vertex colors** | sRGB float [0, 1] | Source u8 [0, 255] values are normalized to [0, 1] in Phase 4. Not linearized — the build phase stores them as FLOAT_COLOR so Blender passes them through as-is |
| **Image pixels** | Raw u8 RGBA, row-major, bottom-to-top | No gamma or color space conversion — stored as decoded from the source format |
| **Bone transforms** | Local-space SRT | `position`, `rotation`, `scale` are relative to parent bone |
| **Bone matrices** | World-space | `world_matrix`, `normalized_world_matrix` etc. are absolute transforms |
| **Mesh vertices** | World-space positions | All vertices are in world space regardless of skin type. Phase 4 transforms RIGID/SINGLE_BONE vertices from bone-local to world space (`parent_world @ vertex`), and ENVELOPE vertices via deformation (`bone_world @ IBM @ vertex`). The compose phase reverses these transforms per skin type |
| **Animation values** | Raw per-channel SRT | Keyframe values are raw rotation/translation/scale from the source. Phase 6's `bake_frame` composes each bone's GX world per frame from these + the `BRBakeSkeleton` rest data, reproducing HSD's aligned scale inheritance under Blender's `inherit_scale='NONE'` |
| **Angles** | Radians | All rotation values throughout the IR |
| **Units** | Meters | All position values are in meters (Blender units). GameCube positions are converted using `GC_TO_METERS = 0.10` on import (Phase 4) and `METERS_TO_GC = 10.0` on export (compose phase). The scale constant is defined in `shared/helpers/scale.py` |

---

## File Organization

```
shared/IR/
  __init__.py             # re-exports all IR types
  enums.py                # all enum definitions
  scene.py                # IRScene (root)
  skeleton.py             # IRModel, IRBone
  geometry.py             # IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights, IRShapeKey
  material.py             # IRMaterial, IRTextureLayer, IRImage, CombinerInput, CombinerStage,
                          # ColorCombiner, FragmentBlending
  animation.py            # IRKeyframe, IRBoneAnimationSet, IRBoneTrack,
                          # IRMaterialAnimationSet, IRMaterialTrack, IRTextureUVTrack,
                          # IRShapeAnimationSet, IRShapeTrack
  constraints.py          # IRIKConstraint, IRBoneReposition, IRCopyLocationConstraint,
                          # IRTrackToConstraint, IRCopyRotationConstraint, IRLimitConstraint
  lights.py               # IRLight
  camera.py               # IRCamera, IRCameraKeyframes
  fog.py                  # IRFog (stub)
  collision.py            # IRCollisionScene, IRCollisionEntry, IRCollisionMesh,
                          # IRCollisionFace — a separate root, not part of IRScene
```

---

## Scene Root

**File:** `shared/IR/scene.py`

```python
@dataclass
class IRScene:
    models: list[IRModel]
    lights: list[IRLight]
    cameras: list[IRCamera]
    fogs: list[IRFog]
```

---

## Skeleton & Model

**File:** `shared/IR/skeleton.py`

```python
@dataclass
class IRModel:
    name: str
    bones: list[IRBone]
    meshes: list[IRMesh]
    bone_animations: list[IRBoneAnimationSet]
    material_animations: list[IRMaterialAnimationSet]
    shape_animations: list[IRShapeAnimationSet]
    # Constraints — separate typed list per constraint kind
    ik_constraints: list[IRIKConstraint]
    copy_location_constraints: list[IRCopyLocationConstraint]
    track_to_constraints: list[IRTrackToConstraint]
    copy_rotation_constraints: list[IRCopyRotationConstraint]
    limit_rotation_constraints: list[IRLimitConstraint]
    limit_location_constraints: list[IRLimitConstraint]

@dataclass
class IRBone:
    name: str
    parent_index: int | None
    position: tuple[float, float, float]
    rotation: tuple[float, float, float]              # Euler XYZ radians
    scale: tuple[float, float, float]
    inverse_bind_matrix: list[list[float]] | None     # 4x4 matrix
    flags: int
    is_hidden: bool
    inherit_scale: ScaleInheritance
    ik_shrink: bool
    # Pre-computed transforms (4x4 matrices as list[list[float]])
    world_matrix: list[list[float]]
    local_matrix: list[list[float]]
    normalized_world_matrix: list[list[float]]
    normalized_local_matrix: list[list[float]]
    scale_correction: list[list[float]]
    accumulated_scale: tuple[float, float, float]
    mesh_indices: list[int]
    instance_child_bone_index: int | None
```

---

## Geometry

**File:** `shared/IR/geometry.py`

```python
@dataclass
class IRMesh:
    name: str
    vertices: list[tuple[float, float, float]]        # world-space positions
    faces: list[list[int]]
    uv_layers: list[IRUVLayer]
    color_layers: list[IRColorLayer]
    normals: list[tuple[float, float, float]] | None   # per-loop
    material: IRMaterial | None
    bone_weights: IRBoneWeights | None
    shape_keys: list[IRShapeKey] | None
    is_hidden: bool
    parent_bone_index: int
    local_matrix: list[list[float]] | None

@dataclass
class IRUVLayer:
    name: str
    uvs: list[tuple[float, float]]                    # per-loop, V already flipped

@dataclass
class IRColorLayer:
    name: str
    colors: list[tuple[float, float, float, float]]   # per-loop RGBA

@dataclass
class IRBoneWeights:
    type: SkinType                                     # WEIGHTED, SINGLE_BONE, RIGID
    assignments: list[tuple[int, list[tuple[str, float]]]] | None
    bone_name: str | None
    deformed_vertices: list[tuple[float, float, float]] | None
    deformed_normals: list[tuple[float, float, float]] | None

@dataclass
class IRShapeKey:
    name: str
    vertex_positions: list[tuple[float, float, float]]
```

---

## Material

**File:** `shared/IR/material.py`

```python
@dataclass
class IRMaterial:
    diffuse_color: tuple[float, float, float, float]
    ambient_color: tuple[float, float, float, float]
    specular_color: tuple[float, float, float, float]
    alpha: float
    shininess: float
    color_source: ColorSource
    alpha_source: ColorSource
    lighting: LightingModel
    enable_specular: bool
    is_translucent: bool
    texture_layers: list[IRTextureLayer]
    fragment_blending: FragmentBlending | None

@dataclass
class IRTextureLayer:
    image: IRImage
    coord_type: CoordType
    uv_index: int
    rotation: tuple[float, float, float]
    scale: tuple[float, float, float]
    translation: tuple[float, float, float]
    wrap_s: WrapMode
    wrap_t: WrapMode
    repeat_s: int
    repeat_t: int
    interpolation: TextureInterpolation | None
    color_blend: LayerBlendMode
    alpha_blend: LayerBlendMode
    blend_factor: float
    lightmap_channel: LightmapChannel
    is_bump: bool
    combiner: ColorCombiner | None

@dataclass
class IRImage:
    name: str
    width: int
    height: int
    pixels: bytes                                      # raw RGBA u8, row-major, bottom-to-top
    image_id: int
    palette_id: int

@dataclass
class FragmentBlending:
    effect: OutputBlendEffect
    source_factor: BlendFactor
    dest_factor: BlendFactor
    alpha_test_threshold_0: int
    alpha_test_threshold_1: int
    alpha_test_op: int
    depth_compare: int
```

---

## Animation

**File:** `shared/IR/animation.py`

All keyframes are fully decoded into explicit frame/value pairs with interpolation and bezier handles. Keyframe values are raw per-channel SRT — Phase 5 builds the model-wide `BRBakeSkeleton` (rest data + parent-first order), and Phase 6's `bake_frame` composes each bone's GX world per frame and inverts Blender's `inherit_scale='NONE'` forward map to a shear-free pose basis. See [br_specification.md](br_specification.md) § BRBakeSkeleton and [implementation_notes.md](implementation_notes.md) § Scale inheritance.

HSD's aligned scale inheritance is reproduced by that per-frame GX composition (`Rot · diag(accumulated_scale)`), not pre-baked into any single rest matrix — so it stays correct even when an ancestor's scale is animated.

For bones hidden at rest (near-zero scale), Phase 4's `fix_near_zero_bone_matrices` scans every animation's keyframes for a max-abs visible scale and uses that for a numerically stable rest matrix. All transitive descendants are rebuilt through `_compose_bone_transforms` so the full six-field transform record stays consistent (see implementation_notes.md § "Near-zero-rest-scale rebind").

```python
@dataclass
class IRKeyframe:
    frame: float
    value: float
    interpolation: Interpolation                       # CONSTANT, LINEAR, BEZIER
    handle_left: tuple[float, float] | None            # (frame, value) for Bezier
    handle_right: tuple[float, float] | None
    slope_in: float | None                             # incoming tangent (derivative)
    slope_out: float | None                            # outgoing tangent (derivative)

@dataclass
class IRBoneTrack:
    bone_name: str
    bone_index: int
    rotation: list[list[IRKeyframe]]                   # [X, Y, Z] channels
    location: list[list[IRKeyframe]]                   # [X, Y, Z] channels
    scale: list[list[IRKeyframe]]                      # [X, Y, Z] channels
    rest_local_matrix: list[list[float]]               # 4x4, format-specific corrections pre-applied
    rest_rotation: tuple[float, float, float]          # raw rest SRT (for missing channel fill)
    rest_position: tuple[float, float, float]
    rest_scale: tuple[float, float, float]
    # Path animation
    spline_path: IRSplinePath | None

@dataclass
class IRBoneAnimationSet:
    name: str
    tracks: list[IRBoneTrack]
    loop: bool
    is_static: bool

@dataclass
class IRMaterialTrack:
    material_mesh_name: str
    diffuse_r: list[IRKeyframe] | None                 # sRGB [0-1], linearized in build phase
    diffuse_g: list[IRKeyframe] | None
    diffuse_b: list[IRKeyframe] | None
    alpha: list[IRKeyframe] | None
    texture_uv_tracks: list[IRTextureUVTrack]
    loop: bool

@dataclass
class IRTextureUVTrack:
    texture_index: int
    translation_u: list[IRKeyframe] | None
    translation_v: list[IRKeyframe] | None
    scale_u: list[IRKeyframe] | None
    scale_v: list[IRKeyframe] | None
    rotation_x: list[IRKeyframe] | None
    rotation_y: list[IRKeyframe] | None
    rotation_z: list[IRKeyframe] | None

@dataclass
class IRMaterialAnimationSet:
    name: str
    tracks: list[IRMaterialTrack]

@dataclass
class IRShapeTrack:
    bone_name: str
    keyframes: list[IRKeyframe]

@dataclass
class IRShapeAnimationSet:
    name: str
    tracks: list[IRShapeTrack]
```

---

## Constraints

**File:** `shared/IR/constraints.py`

```python
@dataclass
class IRBoneReposition:
    bone_name: str
    bone_length: float                                 # target computes actual offsets

@dataclass
class IRIKConstraint:
    bone_name: str
    chain_length: int
    target_bone: str | None
    pole_target_bone: str | None
    pole_angle: float
    bone_repositions: list[IRBoneReposition]

@dataclass
class IRCopyLocationConstraint:
    bone_name: str
    target_bone: str
    influence: float

@dataclass
class IRTrackToConstraint:
    bone_name: str
    target_bone: str
    track_axis: str
    up_axis: str

@dataclass
class IRCopyRotationConstraint:
    bone_name: str
    target_bone: str
    owner_space: str
    target_space: str

@dataclass
class IRLimitConstraint:
    bone_name: str
    owner_space: str
    min_x: float | None
    max_x: float | None
    min_y: float | None
    max_y: float | None
    min_z: float | None
    max_z: float | None
```

---

## Lights

**File:** `shared/IR/lights.py`

```python
@dataclass
class IRLight:
    name: str
    type: LightType                                    # SUN, POINT, SPOT
    color: tuple[float, float, float]
    position: tuple[float, float, float] | None
    target_position: tuple[float, float, float] | None
```

---

## Camera

```python
class CameraProjection(Enum):
    PERSPECTIVE = "PERSPECTIVE"
    ORTHO = "ORTHO"

@dataclass
class IRCameraKeyframes:
    """Decoded animation keyframes for one camera animation clip."""
    name: str
    eye_x: list[IRKeyframe] | None = None
    eye_y: list[IRKeyframe] | None = None
    eye_z: list[IRKeyframe] | None = None
    target_x: list[IRKeyframe] | None = None
    target_y: list[IRKeyframe] | None = None
    target_z: list[IRKeyframe] | None = None
    roll: list[IRKeyframe] | None = None
    fov: list[IRKeyframe] | None = None
    near: list[IRKeyframe] | None = None
    far: list[IRKeyframe] | None = None
    end_frame: float = 0.0
    loop: bool = False

@dataclass
class IRCamera:
    name: str
    projection: CameraProjection
    position: tuple[float, float, float] | None = None
    target_position: tuple[float, float, float] | None = None
    roll: float = 0.0
    near: float = 0.1
    far: float = 1000.0
    field_of_view: float = 60.0   # vertical FOV in degrees
    aspect: float = 1.333
    animations: list[IRCameraKeyframes] = field(default_factory=list)
```

- `projection`: PERSPECTIVE (from COBJ_PROJECTION_PERSPECTIVE/FRUSTUM) or ORTHO
- `position`: camera eye position in GC world coordinates (from WObject)
- `target_position`: camera interest/look-at point (from WObject)
- `field_of_view`: vertical FOV in degrees for perspective; ortho_scale for orthographic
- `viewport`/`scissor`/`up_vector` from the Camera node are not stored (GC screen-space artifacts)

## Fog (stub)

```python
@dataclass
class IRFog:
    name: str
```

No fog data found in tested models. Stub retained for future use.

## Particles

Fully **semantic and platform-agnostic** — no source-format opcodes, header
words, or GX register state. The describe phase summarizes GPT1 bytecode into
this vocabulary (lossily); compose synthesizes fresh bytecode from it. The IR
may carry core particle features a given target cannot fully represent
(e.g. trail rendering, velocity-stretched billboards) — targets approximate
or ignore what they can't express.

```python
@dataclass
class IRParticleSystem:
    emitters: list[IRParticleEmitter]
    textures: list[IRParticleTexture]

@dataclass
class IRParticleEmitter:
    name: str
    emit_duration: float                 # frames the emitter keeps spawning
    max_particles: int
    particle_lifetime: IRRandomScalar    # frames, base ± spread
    looping: bool                        # per-particle animation cycles until death
    emission: IRParticleEmission         # rate (particles/frame) + bursts
    birth: IRParticleBirth               # position/velocity/size/color randomness
    color_over_life: list[IRColorStop]   # sRGB gradient, age normalized [0,1]
    size_over_life: list[IRScalarKey]    # absolute size keys, age normalized
    rotation: IRParticleRotation         # initial angle / rate / accel (radians)
    forces: IRParticleForces             # gravity vector (m/frame^2), drag
    texture: IRParticleTextureAnim       # flip-book frames + sampling state
    render: IRParticleRender             # blend / billboard / depth / trail
    sub_emitters: list[IRSubEmitter]     # (age, emitter_ref, count, inherit_velocity)

@dataclass
class IRParticleTexture:
    width: int
    height: int
    pixels: bytes                    # Decoded RGBA u8, bottom-to-top

@dataclass
class IRParticleEmitEvent:           # on IRBoneTrack.particle_emits
    frame: float                     # clip-local frame
    emitter_ref: int                 # index into IRParticleSystem.emitters
```

- Randomness is uniform `base ± spread` (`IRRandomScalar` / `IRRandomVec3`);
  positions/velocities are meters (Y-up, per frame); colors sRGB [0,1];
  over-life keys/stops use normalized age [0,1].
- The GPT1 leg is deliberately lossy: opcodes with no generic equivalent
  (joint forces, GX register color ops, native callbacks, palette swaps) are
  dropped with a debug log; the source's dual-clock ramp timing is flattened
  to hold+target keys. Compose synthesizes a fresh instruction stream from
  the curves — never byte-reproduction.
- Generator→bone binding is animation data, not emitter state:
  `IRParticleEmitEvent`s live on the owning bone's `IRBoneTrack` (the bone
  that fires the event is the attach point; the spawned emitter follows it).
- Phase 5/6 build the emitters as real Blender objects (`BRParticleSystem` →
  one geometry-node-driven mesh per emitter, ColorRamp/Float-Curve over-life
  gradients) and the emit events as CONSTANT keys on each firing pose bone's
  `particle_emit` property. The export read-back (Blender → BR) is the
  remaining leg. See [exporter_setup.md](exporter_setup.md#particles-gpt1).

---

## Map Collision

Collision (`.ccd`) has its own IR root. It is **not** reachable from `IRScene`
— the whole path (extract → parse → describe → plan → build) runs beside the
model pipeline and shares only the container extraction step.

```python
class IRCollisionScene:
    name: str
    entries: list[IRCollisionEntry]

class IRCollisionEntry:
    index: int                       # addressed from outside the file, so it is data
    meshes: list[IRCollisionMesh]    # in file slot order, absent subsystems omitted
    position/rotation/scale: tuple[float, float, float]
    is_dynamic: bool                 # entry flag bit 0
    npc_shares_hit: bool             # see below

class IRCollisionMesh:
    subsystem: CollisionSubsystem    # WALK / WALL / ZONE_TRIGGER / BUTTON_TRIGGER
                                     # / NPC_WALL / SUN
    vertices: list[tuple[float, float, float]]   # Y-up world space, meters, welded
    faces: list[IRCollisionFace]

class IRCollisionFace:
    indices: tuple[int, int, int]
    edge_mask: int = 0b111           # WALL / NPC_WALL / ZONE_TRIGGER
    region_id: int = 0               # ZONE_TRIGGER / BUTTON_TRIGGER — the
                                     # InteractionPoints key
    layer_a: int = 0xF               # WALK — 0xF matches any layer
    layer_b: int = 0xF
    surface_a: int = 0               # WALK — surface/effect nibbles
    surface_b: int = 0
```

`CollisionSubsystem` (named for behaviour, not for the engine's own `walk /
hit / thru / check / hit_npc / sun` slot names) and the format's layout
constants live in `shared/Constants/collision.py`, which both the binary layer
(`shared/Collision/`) and this IR import — neither depends on the other.

Positions are scaled by `GC_TO_METERS` in describe, like every other IR
position, so the overlay lines up with an imported room model.

What the IR drops, because it is recomputable: **poly normals** (winding gives
`normalize(cross(v1 - v0, v2 - v0))` back exactly) and the **XZ lookup grid**
(derived from the triangle bounds). What it normalises: the three independent
corners each poly stores on disk are **welded** into an indexed mesh; a poly
whose welded corners repeat an earlier face's keeps private vertices, since
Blender can only hold one face per vertex set.

**NPC walls are stored as a difference.** `npc_shares_hit` set means the NPC
wall mesh is every player wall *plus* whatever the `NPC_WALL` mesh holds —
usually nothing, so no `NPC_WALL` mesh is emitted at all. Cleared, any
`NPC_WALL` mesh stands alone. Reconstruction is exact; only poly *order* can
differ, and only where the original interleaved its extra NPC walls with the
shared ones. See [collision_format.md](collision_format.md) § Blender import
mapping.
