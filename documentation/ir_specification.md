# Intermediate Representation (IR) Specification

The IR is the output of Phase 4 (Scene Description) and the input to Phase 5 (Build). It is a pure-Python dataclass hierarchy with no dependencies on `bpy` or the Node system.

> **Note:** Shiny variant data bypasses the IR entirely. Raw shiny parameters are extracted in Phase 1 (extract) and passed directly to Phase 6 (post_process), which applies them to Blender materials after the main build is complete.

**Design principles:**
- All types are `@dataclass` from the standard library
- All categorical values use Python `enum.Enum`
- No mutable shared state — each IR instance is a self-contained snapshot
- Materials store abstract rendering parameters, not target-specific shader graphs
- Animation keyframes are fully decoded (frame/value/interpolation/handles) — not compressed bytes, not target-baked values
- Image pixels are raw u8 bytes — float conversion happens in the build phase
- Platform-agnostic: no source-format quirks (GameCube) or target-format quirks (Blender) — Phase 4 strips the former, Phase 5 applies the latter

---

## Conventions & Coordinate Spaces

The IR uses standard, widely-adopted conventions so that any build phase can consume it without needing to know about the original game format.

| Property | Convention | Notes |
|---|---|---|
| **Coordinate system** | Y-up, right-handed | GameCube uses Y-up natively; the π/2 X-rotation for Blender's Z-up is applied in Phase 5 at the armature level |
| **Rotation** | Euler XYZ, radians | Stored as `(rx, ry, rz)` tuples |
| **Matrices** | 4×4, row-major | Stored as `list[list[float]]` (4 rows of 4 floats) |
| **UV origin** | Bottom-left (OpenGL convention) | Phase 4 flips V from GameCube's top-left origin: `v = 1 - scale_v - v` |
| **UV animation** | Bottom-left, V-flipped in Phase 4 | Animated `translation_v` keyframes are corrected using the static or animated `scale_v` value at each keyframe's frame |
| **Color space** | sRGB [0, 1] | Diffuse/ambient/specular/vertex colors are normalized from u8 [0, 255] to float [0, 1] but remain in sRGB space. Linearization for Blender happens in Phase 5 (build) |
| **Vertex colors** | sRGB float [0, 1] | Source u8 [0, 255] values are normalized to [0, 1] in Phase 4. Not linearized — the build phase stores them as FLOAT_COLOR so Blender passes them through as-is |
| **Image pixels** | Raw u8 RGBA, row-major, bottom-to-top | No gamma or color space conversion — stored as decoded from the source format |
| **Bone transforms** | Local-space SRT | `position`, `rotation`, `scale` are relative to parent bone |
| **Bone matrices** | World-space | `world_matrix`, `normalized_world_matrix` etc. are absolute transforms |
| **Mesh vertices** | World-space positions | All vertices are in world space regardless of skin type. Phase 4 transforms RIGID/SINGLE_BONE vertices from bone-local to world space (`parent_world @ vertex`), and ENVELOPE vertices via deformation (`bone_world @ IBM @ vertex`). The compose phase reverses these transforms per skin type |
| **Animation values** | Raw per-channel SRT | Keyframe values are raw rotation/translation/scale from the source. Phase 5 composes them via plain `T @ R @ S`. Format-specific corrections (e.g. aligned scale inheritance) are pre-baked into `rest_local_matrix` by Phase 4 |
| **Angles** | Radians | All rotation values throughout the IR |
| **Units** | Unitless (source scale) | No unit conversion is applied; 1 unit = 1 source unit |

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
  camera.py               # IRCamera (stub)
  fog.py                  # IRFog (stub)
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

All keyframes are fully decoded into explicit frame/value pairs with interpolation and bezier handles. Keyframe values are raw per-channel SRT — Phase 5 composes them into matrices via plain `T @ R @ S` (no format-specific corrections needed).

Format-specific corrections (e.g. HSD's aligned scale inheritance) are pre-baked into `rest_local_matrix` by Phase 4. The build phase uses: `Bmtx = rest_local_matrix.inv() @ animated_SRT_matrix`. This keeps format-specific logic in the describe phase.

For bones hidden at rest (near-zero scale), Phase 4 scans animation keyframes to find the intended "visible" scale and uses that for a numerically stable rest matrix.

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

## Camera & Fog (stubs)

```python
@dataclass
class IRCamera:
    name: str

@dataclass
class IRFog:
    name: str
```
