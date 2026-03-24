# Intermediate Representation (IR) Specification

The IR is the output of Phase 4 (Scene Description) and the input to Phase 5A (Build) and Phase 5B (Export). It is a pure-Python dataclass hierarchy with no dependencies on `bpy` or the Node system.

**Design principles:**
- All types are `@dataclass` from the standard library
- All categorical values use Python `enum.Enum`
- No mutable shared state — each IR instance is a self-contained snapshot
- Fully serializable (JSON/YAML for debugging, pickle for caching)
- The IR is the intersection of source format capabilities and common 3D engine features
- Materials store abstract rendering parameters, not target-specific shader graphs

---

## File Organization

```
shared/IR/
  __init__.py             # re-exports all IR types
  enums.py                # all enum definitions
  scene.py                # IRScene (root)
  skeleton.py             # IRModel, IRBone
  geometry.py             # IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights, IRShapeKey
  material.py             # IRMaterial, IRTextureLayer, IRImage, ColorCombiner, FragmentBlending
  animation.py            # IRKeyframe, IRBoneAnimationSet, IRBoneTrack,
                          # IRMaterialAnimationSet, IRMaterialTrack, IRTextureUVTrack,
                          # IRShapeAnimationSet, IRShapeTrack
  constraints.py          # IRIKConstraint, IRCopyLocationConstraint, IRTrackToConstraint,
                          # IRCopyRotationConstraint, IRLimitConstraint, IRBoneReposition
  lights.py               # IRLight
  camera.py               # IRCamera (stub)
  fog.py                  # IRFog (stub)

shared/helpers/
  __init__.py
  math_shim.py            # Matrix/Vector/Euler (mathutils or pure Python fallback)
  srgb.py                 # sRGB <-> linear conversion
  keyframe_decoder.py     # decode_fobjdesc() — pure-data keyframe decoding
```

---

## Enums

**File:** `shared/IR/enums.py`

```python
from enum import Enum

class CoordType(Enum):
    """Texture coordinate generation mode."""
    UV = "UV"
    REFLECTION = "REFLECTION"
    SPECULAR_HIGHLIGHT = "SPECULAR_HIGHLIGHT"
    SHADOW = "SHADOW"
    CEL_SHADING = "CEL_SHADING"
    GRADATION = "GRADATION"

class WrapMode(Enum):
    """Texture wrapping mode."""
    CLAMP = "CLAMP"
    REPEAT = "REPEAT"
    MIRROR = "MIRROR"

class Interpolation(Enum):
    """Keyframe interpolation type."""
    CONSTANT = "CONSTANT"
    LINEAR = "LINEAR"
    BEZIER = "BEZIER"

class TextureInterpolation(Enum):
    """Texture sampling interpolation."""
    CLOSEST = "Closest"
    LINEAR = "Linear"
    CUBIC = "Cubic"

class LightType(Enum):
    """Light source type."""
    SUN = "SUN"
    POINT = "POINT"
    SPOT = "SPOT"

class SkinType(Enum):
    """Mesh skinning/deformation mode."""
    WEIGHTED = "WEIGHTED"            # Multi-bone weighted deformation
    SINGLE_BONE = "SINGLE_BONE"     # Single-bone deformation
    RIGID = "RIGID"                  # Rigid attachment to one bone

class ScaleInheritance(Enum):
    """Bone scale inheritance mode."""
    ALIGNED = "ALIGNED"

# --- Material enums ---

class ColorSource(Enum):
    """Where the base diffuse color or alpha comes from."""
    MATERIAL = "MATERIAL"            # Material constant color / alpha
    VERTEX = "VERTEX"                # Vertex color attribute / vertex alpha
    BOTH = "BOTH"                    # Combine material and vertex

class LightingModel(Enum):
    """How the surface responds to scene lighting."""
    LIT = "LIT"                      # Standard diffuse lighting
    UNLIT = "UNLIT"                  # No lighting response (flat/emissive)

class LayerBlendMode(Enum):
    """How a texture layer composites onto the accumulated color or alpha.
    Analogous to layer blend modes in compositing software."""
    NONE = "NONE"                    # Layer disabled / no effect
    PASS = "PASS"                    # Layer skipped (no contribution)
    REPLACE = "REPLACE"              # output = layer (ignore previous)
    MULTIPLY = "MULTIPLY"            # output = previous * layer
    ADD = "ADD"                      # output = previous + layer
    SUBTRACT = "SUBTRACT"            # output = previous - layer
    MIX = "MIX"                      # output = lerp(previous, layer, blend_factor)
    ALPHA_MASK = "ALPHA_MASK"        # output = lerp(previous, layer, layer.alpha)
    RGB_MASK = "RGB_MASK"            # output = lerp(previous, layer, layer.color)

class LightmapChannel(Enum):
    """Which lighting channel a texture contributes to."""
    NONE = "NONE"                    # Default: treated as diffuse
    DIFFUSE = "DIFFUSE"
    SPECULAR = "SPECULAR"
    AMBIENT = "AMBIENT"
    EXTENSION = "EXTENSION"
    SHADOW = "SHADOW"

class CombinerInputSource(Enum):
    """What value feeds into a color combiner input slot."""
    ZERO = "ZERO"                    # Constant 0.0
    ONE = "ONE"                      # Constant 1.0 (color only)
    HALF = "HALF"                    # Constant 0.5 (color only)
    TEXTURE_COLOR = "TEXTURE_COLOR"  # Sampled texture RGB
    TEXTURE_ALPHA = "TEXTURE_ALPHA"  # Sampled texture alpha
    CONSTANT = "CONSTANT"            # Constant register (see CombinerInput.value)
    REGISTER_0 = "REGISTER_0"       # Combiner register 0
    REGISTER_1 = "REGISTER_1"       # Combiner register 1

class CombinerOp(Enum):
    """Color combiner arithmetic operation."""
    ADD = "ADD"                      # lerp(A,B,C) + D
    SUBTRACT = "SUBTRACT"           # D - lerp(A,B,C)
    COMPARE_R8_GT = "COMPARE_R8_GT"
    COMPARE_R8_EQ = "COMPARE_R8_EQ"
    COMPARE_GR16_GT = "COMPARE_GR16_GT"
    COMPARE_GR16_EQ = "COMPARE_GR16_EQ"
    COMPARE_BGR24_GT = "COMPARE_BGR24_GT"
    COMPARE_BGR24_EQ = "COMPARE_BGR24_EQ"
    COMPARE_RGB8_GT = "COMPARE_RGB8_GT"
    COMPARE_RGB8_EQ = "COMPARE_RGB8_EQ"

class CombinerBias(Enum):
    """Bias added after the combiner operation."""
    ZERO = "ZERO"                    # No bias
    PLUS_HALF = "+0.5"               # Add 0.5
    MINUS_HALF = "-0.5"              # Subtract 0.5

class CombinerScale(Enum):
    """Scale factor applied to the combiner result."""
    SCALE_1 = "1"
    SCALE_2 = "2"
    SCALE_4 = "4"
    SCALE_HALF = "0.5"

class OutputBlendEffect(Enum):
    """Resolved semantic blend effect for framebuffer compositing."""
    OPAQUE = "OPAQUE"
    ALPHA_BLEND = "ALPHA_BLEND"
    INVERSE_ALPHA_BLEND = "INVERSE_ALPHA_BLEND"
    ADDITIVE = "ADDITIVE"
    ADDITIVE_ALPHA = "ADDITIVE_ALPHA"
    ADDITIVE_INV_ALPHA = "ADDITIVE_INV_ALPHA"
    MULTIPLY = "MULTIPLY"
    SRC_ALPHA_ONLY = "SRC_ALPHA_ONLY"
    INV_SRC_ALPHA_ONLY = "INV_SRC_ALPHA_ONLY"
    INVISIBLE = "INVISIBLE"
    BLACK = "BLACK"
    WHITE = "WHITE"
    INVERT = "INVERT"
    CUSTOM = "CUSTOM"                # See source_factor/dest_factor

class BlendFactor(Enum):
    """Source/destination blend factor for fragment blending."""
    ZERO = "ZERO"
    ONE = "ONE"
    SRC_COLOR = "SRC_COLOR"
    INV_SRC_COLOR = "INV_SRC_COLOR"
    SRC_ALPHA = "SRC_ALPHA"
    INV_SRC_ALPHA = "INV_SRC_ALPHA"
    DST_ALPHA = "DST_ALPHA"
    INV_DST_ALPHA = "INV_DST_ALPHA"
```

---

## Scene Root

**File:** `shared/IR/scene.py`

```python
@dataclass
class IRScene:
    """Root of the IR. One per import operation."""
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
    """One skeleton with its geometry, materials, and animations."""
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
    # Coordinate system transform applied to the skeleton root
    coordinate_rotation: tuple[float, float, float]   # Euler XYZ radians (pi/2, 0, 0)

@dataclass
class IRBone:
    """One bone in a flat list. Parent relationship via index."""
    name: str
    parent_index: int | None                          # index into IRModel.bones, None for roots
    # Rest-pose transform
    position: tuple[float, float, float]
    rotation: tuple[float, float, float]              # Euler XYZ radians
    scale: tuple[float, float, float]
    inverse_bind_matrix: list[list[float]] | None     # 4x4 matrix or None
    # Flags
    flags: int                                        # source format bone flags (preserved for round-trip)
    is_hidden: bool
    inherit_scale: ScaleInheritance
    ik_shrink: bool                                   # shrink bone for IK solver accuracy
    # Pre-computed transforms (all 4x4 matrices stored as list[list[float]])
    world_matrix: list[list[float]]                   # accumulated world transform
    local_matrix: list[list[float]]                   # local SRT matrix
    normalized_world_matrix: list[list[float]]        # normalized world (for rest-pose binding)
    normalized_local_matrix: list[list[float]]        # normalized local (for rest-pose binding)
    scale_correction: list[list[float]]               # scale compensation matrix for animation baking
    accumulated_scale: tuple[float, float, float]     # parent-chain accumulated scale
    # Geometry binding
    mesh_indices: list[int]                           # indices into IRModel.meshes
    # Instancing
    instance_child_bone_index: int | None             # if instanced bone, index of child to copy
```

---

## Geometry

**File:** `shared/IR/geometry.py`

```python
@dataclass
class IRMesh:
    """One geometry batch with its material."""
    name: str
    vertices: list[tuple[float, float, float]]        # world-space positions
    faces: list[list[int]]                            # vertex index lists per face
    uv_layers: list[IRUVLayer]                        # up to 8 UV layers
    color_layers: list[IRColorLayer]                  # color + alpha layers
    normals: list[tuple[float, float, float]] | None  # per-loop normals, or None
    material: IRMaterial
    bone_weights: IRBoneWeights | None
    shape_keys: list[IRShapeKey] | None
    is_hidden: bool                                   # hidden in viewport + render
    parent_bone_index: int                            # index into IRModel.bones
    local_matrix: list[list[float]]                   # 4x4 local transform

@dataclass
class IRUVLayer:
    """One UV coordinate layer."""
    name: str                                         # e.g. 'uvtex_0', 'uvtex_1'
    uvs: list[tuple[float, float]]                    # per-loop UV coordinates (V already flipped)

@dataclass
class IRColorLayer:
    """One vertex color or alpha layer."""
    name: str                                         # e.g. 'color_0', 'alpha_0'
    colors: list[tuple[float, float, float, float]]   # per-loop RGBA values

@dataclass
class IRBoneWeights:
    """Vertex-to-bone weight assignments for mesh skinning."""
    type: SkinType
    # For WEIGHTED: per-vertex bone assignments
    #   Each entry is (vertex_index, [(bone_name, weight), ...])
    assignments: list[tuple[int, list[tuple[str, float]]]] | None
    # For SINGLE_BONE/RIGID: single bone name
    bone_name: str | None
    # Pre-computed deformed geometry (weighted transforms already applied)
    deformed_vertices: list[tuple[float, float, float]] | None
    deformed_normals: list[tuple[float, float, float]] | None

@dataclass
class IRShapeKey:
    """One morph target / blend shape."""
    name: str
    vertex_positions: list[tuple[float, float, float]]  # per-vertex positions
```

---

## Material

**File:** `shared/IR/material.py`

Materials store abstract rendering parameters. The target-specific rendering setup (shader graphs, render state, etc.) is constructed in Phase 5A. This preserves full fidelity for round-trip export and keeps the IR target-independent.

```python
@dataclass
class IRMaterial:
    """Complete material description."""
    # Surface colors (linearized RGBA, 0-1)
    diffuse_color: tuple[float, float, float, float]
    ambient_color: tuple[float, float, float, float]
    specular_color: tuple[float, float, float, float]
    alpha: float                                      # material alpha (0-1)
    shininess: float
    # Rendering configuration
    color_source: ColorSource                         # where base color comes from
    alpha_source: ColorSource                         # where base alpha comes from
    lighting: LightingModel                           # lit or unlit
    enable_specular: bool                             # whether specular highlights are active
    is_translucent: bool                              # transparency hint
    # Texture layers (ordered, only enabled textures)
    texture_layers: list[IRTextureLayer]
    # Fragment blending (how material composites with the framebuffer)
    fragment_blending: FragmentBlending | None

@dataclass
class IRTextureLayer:
    """One texture in the material's layer stack."""
    image: IRImage
    # UV / coordinate generation
    coord_type: CoordType                             # UV, REFLECTION, etc.
    uv_index: int                                     # 0-based UV layer index
    # Transform
    rotation: tuple[float, float, float]              # texture rotation XYZ
    scale: tuple[float, float, float]                 # texture scale
    translation: tuple[float, float, float]           # texture offset (UV space)
    # Wrapping
    wrap_s: WrapMode                                  # horizontal wrap
    wrap_t: WrapMode                                  # vertical wrap
    repeat_s: int                                     # horizontal repeat count
    repeat_t: int                                     # vertical repeat count
    # Sampling
    interpolation: TextureInterpolation | None        # sampling filter
    # How this layer composites onto accumulated color/alpha
    color_blend: LayerBlendMode                       # color compositing operation
    alpha_blend: LayerBlendMode                       # alpha compositing operation
    blend_factor: float                               # for MIX mode (0-1)
    # Which lighting channel this texture affects
    lightmap_channel: LightmapChannel
    is_bump: bool                                     # bump/normal map
    # Optional per-texture color combiner
    combiner: ColorCombiner | None

@dataclass
class IRImage:
    """Decoded image data ready for use."""
    name: str
    width: int
    height: int
    pixels: list[float]                               # normalized RGBA, row-major
    image_id: int                                     # for deduplication
    palette_id: int                                   # for deduplication

@dataclass
class CombinerInput:
    """One input to the color combiner formula."""
    source: CombinerInputSource
    channel: str | None = None                        # "RGB", "RRR", "GGG", "BBB", "AAA",
                                                      # "R", "G", "B", "A", or None
    value: tuple[float, float, float, float] | None = None  # pre-resolved RGBA for
                                                             # CONSTANT/REGISTER sources

@dataclass
class CombinerStage:
    """One channel (color or alpha) of the color combiner.
    Computes: clamp(scale * (lerp(input_a, input_b, input_c) ± input_d + bias))
    Where lerp(a, b, c) = a * (1 - c) + b * c"""
    input_a: CombinerInput                            # first lerp operand
    input_b: CombinerInput                            # second lerp operand
    input_c: CombinerInput                            # lerp blend factor
    input_d: CombinerInput                            # added/subtracted after lerp
    operation: CombinerOp
    bias: CombinerBias
    scale: CombinerScale
    clamp: bool

@dataclass
class ColorCombiner:
    """Per-texture color/alpha combiner configuration.
    Implements the generalized formula: clamp(scale * (lerp(A,B,C) ± D + bias))"""
    color: CombinerStage | None                       # None if color combiner inactive
    alpha: CombinerStage | None                       # None if alpha combiner inactive

@dataclass
class FragmentBlending:
    """How the material's output composites with the framebuffer.
    The 'effect' field captures the resolved semantic meaning.
    The 'source_factor' and 'dest_factor' preserve raw configuration
    for CUSTOM effects or round-trip export."""
    effect: OutputBlendEffect
    source_factor: BlendFactor
    dest_factor: BlendFactor
    alpha_test_threshold_0: int                       # 0-255
    alpha_test_threshold_1: int                       # 0-255
    alpha_test_op: int                                # compare operation
    depth_compare: int                                # depth buffer comparison
```

---

## Animation

**File:** `shared/IR/animation.py`

All keyframes are fully decoded from the compressed source format keyframe data into explicit frame/value pairs. No further binary decoding is needed by Phase 5A.

```python
@dataclass
class IRKeyframe:
    """A single keyframe with interpolation data."""
    frame: float
    value: float
    interpolation: Interpolation
    handle_left: tuple[float, float] | None           # (frame, value) for Bezier
    handle_right: tuple[float, float] | None

@dataclass
class IRBoneAnimationSet:
    """One complete bone animation set."""
    name: str
    tracks: list[IRBoneTrack]                         # one entry per animated bone
    loop: bool                                        # loop playback
    is_static: bool                                   # true if all channels are constant (pose)

@dataclass
class IRBoneTrack:
    """Baked animation data for one bone, in bone-local space."""
    bone_name: str
    # Each channel is a list of (frame, value) pairs in bone-local space.
    # Outer list = [X, Y, Z] channels.
    rotation: list[list[tuple[int, float]]]           # [X, Y, Z] Euler channels
    location: list[list[tuple[int, float]]]           # [X, Y, Z] location channels
    scale: list[list[tuple[int, float]]]              # [X, Y, Z] scale channels

@dataclass
class IRMaterialAnimationSet:
    """One material animation set (may span multiple materials)."""
    name: str
    tracks: list[IRMaterialTrack]

@dataclass
class IRMaterialTrack:
    """Animation tracks for a single material."""
    material_mesh_name: str                           # identifies which mesh's material
    diffuse_r: list[IRKeyframe] | None                # linearized from sRGB
    diffuse_g: list[IRKeyframe] | None
    diffuse_b: list[IRKeyframe] | None
    alpha: list[IRKeyframe] | None                    # direct (no sRGB conversion)
    texture_uv_tracks: list[IRTextureUVTrack]
    loop: bool

@dataclass
class IRTextureUVTrack:
    """UV animation for one texture in a material."""
    texture_index: int                                # index into IRMaterial.texture_layers
    translation_u: list[IRKeyframe] | None
    translation_v: list[IRKeyframe] | None
    scale_u: list[IRKeyframe] | None
    scale_v: list[IRKeyframe] | None
    rotation_x: list[IRKeyframe] | None
    rotation_y: list[IRKeyframe] | None
    rotation_z: list[IRKeyframe] | None

@dataclass
class IRShapeAnimationSet:
    """Morph target / blend shape animation set."""
    name: str
    tracks: list[IRShapeTrack]

@dataclass
class IRShapeTrack:
    """Blend weight keyframes for one morph target."""
    bone_name: str                                    # bone whose mesh has morph targets
    keyframes: list[IRKeyframe]                       # blend weight per frame
```

---

## Constraints

**File:** `shared/IR/constraints.py`

Each constraint type has its own dataclass with explicitly typed fields.

```python
@dataclass
class IRIKConstraint:
    """Inverse kinematics constraint."""
    bone_name: str                                    # bone to add constraint to
    chain_length: int                                 # number of bones in IK chain
    target_bone: str | None                           # IK target bone name
    pole_target_bone: str | None                      # pole target bone name
    pole_angle: float                                 # pole angle in radians
    bone_repositions: list[IRBoneReposition]           # position offsets for chain bones

@dataclass
class IRBoneReposition:
    """Bone position offset applied during IK chain setup."""
    bone_name: str
    head_offset: tuple[float, float, float]
    tail_offset: tuple[float, float, float]

@dataclass
class IRCopyLocationConstraint:
    """Position tracking constraint."""
    bone_name: str
    target_bone: str
    influence: float                                  # 0.0 - 1.0

@dataclass
class IRTrackToConstraint:
    """Aim / look-at constraint."""
    bone_name: str
    target_bone: str
    track_axis: str                                   # e.g. 'TRACK_X'
    up_axis: str                                      # e.g. 'UP_Y'

@dataclass
class IRCopyRotationConstraint:
    """Orientation tracking constraint."""
    bone_name: str
    target_bone: str
    owner_space: str                                  # 'WORLD' or 'LOCAL'
    target_space: str                                 # 'WORLD' or 'LOCAL'

@dataclass
class IRLimitConstraint:
    """Rotation or translation limit constraint. The parent list on IRModel
    determines which type (rotation vs. location)."""
    bone_name: str
    owner_space: str                                  # 'LOCAL_WITH_PARENT'
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
    """A light source in the scene."""
    name: str
    type: LightType                                   # SUN, POINT, or SPOT
    color: tuple[float, float, float]                 # RGB (0-1)
    position: tuple[float, float, float] | None       # world position
    target_position: tuple[float, float, float] | None  # look-at target (for SPOT)
    coordinate_rotation: tuple[float, float, float]   # Euler XYZ for coordinate system transform
```

---

## Camera & Fog (stubs)

**File:** `shared/IR/camera.py`

```python
@dataclass
class IRCamera:
    """Camera (stub — not yet implemented)."""
    name: str
```

**File:** `shared/IR/fog.py`

```python
@dataclass
class IRFog:
    """Fog (stub — not yet implemented)."""
    name: str
```

---

## Helper Modules

### Math Shim (`shared/helpers/math_shim.py`)

Provides `Matrix`, `Vector`, and `Euler` classes. When running inside Blender, delegates to `mathutils`. When running outside Blender (e.g. in pytest), falls back to a minimal pure-Python implementation.

Required operations:
- Matrix multiplication (`@` operator)
- Matrix inversion (`.inverted()`, `.inverted_safe()`)
- Matrix decomposition (`.decompose()` -> translation, quaternion, scale)
- Euler conversion (`.to_euler()`)
- Construction: `Matrix.Scale()`, `Matrix.Rotation()`, `Matrix.Translation()`
- Vector normalization, dot product, cross product

### sRGB Conversion (`shared/helpers/srgb.py`)

Pure-Python sRGB-to-linear and linear-to-sRGB single-channel conversion functions. Used by Phase 4 to linearize material colors and animation tracks.

### Keyframe Decoder (`shared/helpers/keyframe_decoder.py`)

Pure-data keyframe decoder. Takes the compressed source format keyframe byte buffer and returns `list[IRKeyframe]` without touching any target-specific APIs. Supports all source interpolation types (constant, linear, spline, slope, key) and all value encoding formats (float, signed/unsigned 16-bit, signed/unsigned 8-bit).

---

## Appendix A: Source Format (DAT/HSD) → IR Mapping

This section documents how each parsed source format node class maps to IR types. Source format terminology (HSD, JOBJ, MOBJ, etc.) appears freely here as this IS the source format mapping reference.

| Source Node | IR Type | Key Transformations |
|-------------|---------|---------------------|
| `ModelSet` | `IRModel` | Root joint tree flattened to `bones` list; `animated_joints` → `bone_animations`; `animated_material_joints` → `material_animations` |
| `Joint` | `IRBone` | SRT fields preserved; `flags` kept as raw int for round-trip; world/local matrices pre-computed; parent tracked by index into flat list |
| `Mesh` (DObject) | (groups `IRMesh` entries) | Links PObject chain to MaterialObject; each PObject becomes one `IRMesh` |
| `PObject` | `IRMesh` | Display list decoded to vertices/faces; vertex attributes split into `uv_layers`, `color_layers`, `normals`; `POBJ_ENVELOPE`→`WEIGHTED`, `POBJ_SKIN`→`SINGLE_BONE`, else→`RIGID` |
| `MaterialObject` | `IRMaterial` | `render_mode` decomposed: bits 0-1→`color_source`, bits 13-14→`alpha_source`, bit 2→`lighting`, bit 3→`enable_specular`, bit 30→`is_translucent`; texture chain filtered to enabled-only `texture_layers` |
| `Texture` (TOBJ) | `IRTextureLayer` | `flags` decomposed: bits 0-3→`coord_type`, bits 4-8→`lightmap_channel`, bits 16-19→`color_blend`, bits 20-23→`alpha_blend`, bit 24→`is_bump`; `source - 4` → 0-based `uv_index` |
| `TextureTEV` | `ColorCombiner` | Raw GX input selectors (GX_CC_*/GX_CA_*) resolved to `CombinerInputSource` enums; `konst`/`tev0`/`tev1` colors normalized and stored in `CombinerInput.value`; `TOBJ_TEVREG_ACTIVE_COLOR_TEV`/`ALPHA_TEV` flags determine which stages are active |
| `PixelEngine` | `FragmentBlending` | (GX_BM_*, GX_BL_*, GX_LO_*) triple resolved to `OutputBlendEffect`; raw factors preserved as `BlendFactor` enums for CUSTOM/round-trip |
| `Image` + `Palette` | `IRImage` | Pixels decoded from GX tile format to normalized RGBA float list; palette applied during decode |
| `AnimationJoint` | `IRBoneAnimationSet` | Parallel tree walk with Joint tree; HSD keyframes (FOBJ) decoded to `(frame, value)` pairs; SRT channels baked through scale correction to bone-local space |
| `MaterialAnimation` | `IRMaterialAnimationSet` | Color tracks linearized (sRGB→linear at 1/255 scale); texture UV tracks (HSD_A_T_*) decoded to keyframe lists |
| `Light` (LOBJ) | `IRLight` | `LOBJ_INFINITE`→SUN, `LOBJ_POINT`→POINT, `LOBJ_SPOT`→SPOT; position/interest WObjects → position/target tuples |
| `Reference` (ROBJ) | `IRIKConstraint` etc. | Reference chain walked; `REFTYPE_JOBJ` sub_type 1→CopyLocation, sub_type 2→TrackTo, sub_type 4→CopyRotation; `REFTYPE_LIMIT`→LimitConstraint; `JOBJ_EFFECTOR`→IKConstraint |

### Key Resolution Steps

**render_mode decomposition:**
```
RENDER_DIFFUSE_MAT (1) → ColorSource.MATERIAL
RENDER_DIFFUSE_VTX (2) → ColorSource.VERTEX
RENDER_DIFFUSE_BOTH (3) → ColorSource.BOTH
RENDER_ALPHA_COMPAT (0) → copy from color_source
RENDER_DIFFUSE bit (4) → LightingModel.LIT / .UNLIT
RENDER_SPECULAR bit (8) → enable_specular
RENDER_XLU bit (1<<30) → is_translucent
```

**TEV input resolution (color):**
```
GX_CC_ZERO (15) → ZERO
GX_CC_ONE (12) → ONE
GX_CC_HALF (13) → HALF
GX_CC_TEXC (8) → TEXTURE_COLOR
GX_CC_TEXA (9) → TEXTURE_ALPHA
TOBJ_TEV_CC_KONST_RGB (0x80) → CONSTANT, channel="RGB"
TOBJ_TEV_CC_KONST_RRR (0x81) → CONSTANT, channel="RRR"
...etc — see Appendix C for full table
```

**PE effect resolution:**
```
BM_NONE → OPAQUE
BM_BLEND + SRCALPHA + INVSRCALPHA → ALPHA_BLEND
BM_BLEND + ONE + ONE → ADDITIVE
BM_BLEND + DSTCLR + ZERO → MULTIPLY
BM_LOGIC + LO_NOOP → INVISIBLE
...etc — see Appendix C OutputBlendEffect table
```

---

## Appendix B: IR → Target Scene (Blender) Mapping

This section documents how each IR type maps to Blender API objects. Blender terminology appears freely here as this IS the Blender mapping reference.

| IR Type | Blender Objects Created | Key API Calls |
|---------|------------------------|---------------|
| `IRModel` | Armature object + Armature data | `bpy.data.armatures.new()`, `bpy.data.objects.new()`, coordinate system rotation via `matrix_basis` |
| `IRBone` | Edit bone (EDIT mode) | `armature.edit_bones.new()`, `bone.matrix`, `bone.inherit_scale`, `bone.parent` |
| `IRMesh` | Mesh data + Mesh object | `bpy.data.meshes.new()`, `mesh.from_pydata()`, vertex groups, armature modifier, UV/color layers |
| `IRMaterial` | Material + Shader node tree | `bpy.data.materials.new()`, node tree built from `color_source`/`lighting`/`texture_layers`/`fragment_blending` |
| `IRTextureLayer` | ShaderNodeTexImage + ShaderNodeMapping + blend nodes | `coord_type` → UVMap/TexCoord node; `color_blend`/`alpha_blend` → MixRGB/Math nodes; `combiner` → node chain |
| `ColorCombiner` | Chain of MixRGB/Math shader nodes | Formula `lerp(A,B,C) ± D` built as subtract→multiply→add node chain |
| `FragmentBlending` | `material.blend_method` + transparency shader nodes | `effect` determines blend_method ('BLEND','HASHED') and optional transparent/emission shaders |
| `IRImage` | Blender image | `bpy.data.images.new()`, `image.pixels`, `image.pack()` |
| `IRBoneAnimationSet` | Action + F-Curves + Keyframes | `bpy.data.actions.new()`, `action.fcurves.new()`, `keyframe_points.insert()`, optional CYCLES modifier for `loop` |
| `IRMaterialAnimationSet` | Action per material + NLA tracks | Material fcurves targeting `node_tree.nodes[...].outputs[0].default_value`; pushed to NLA strips |
| `IRBoneTrack` | 9 F-Curves (rot XYZ, loc XYZ, scale XYZ) | Data paths: `pose.bones["name"].rotation_euler/location/scale` |
| `IRLight` | Light data + Light object (+ empty target for SPOT) | `bpy.data.lights.new()`, TRACK_TO constraint for aim target |
| `IRIKConstraint` | IK constraint on pose bone | `constraints.new(type='IK')`, `chain_count`, `target`, `pole_target` |
| `IRCopyLocationConstraint` | Copy Location constraint on pose bone | `constraints.new(type='COPY_LOCATION')` |
| `IRTrackToConstraint` | Track To constraint on pose bone | `constraints.new(type='TRACK_TO')` |
| `IRCopyRotationConstraint` | Copy Rotation constraint on pose bone | `constraints.new(type='COPY_ROTATION')` |
| `IRLimitConstraint` | Limit Rotation / Limit Location constraint | `constraints.new(type='LIMIT_ROTATION')` or `constraints.new(type='LIMIT_LOCATION')` |

---

## Appendix C: Enum Value Mapping Tables

Per-value mapping for every IR enum, showing the source format constant and target (Blender) equivalent where applicable.

### LayerBlendMode

| IR Value | DAT/HSD Constant | Blender Equivalent | Formula |
|----------|-------------------|--------------------|---------|
| NONE | TEX_COLORMAP_NONE / TEX_ALPHAMAP_NONE | (skipped, no node) | — |
| PASS | TEX_COLORMAP_PASS / TEX_ALPHAMAP_PASS | (skipped, no node) | previous unchanged |
| REPLACE | TEX_COLORMAP_REPLACE / TEX_ALPHAMAP_REPLACE | ShaderNodeMixRGB(ADD, fac=0) | output = layer |
| MULTIPLY | TEX_COLORMAP_MODULATE / TEX_ALPHAMAP_MODULATE | ShaderNodeMixRGB(MULTIPLY) / ShaderNodeMath(MULTIPLY) | output = previous × layer |
| ADD | TEX_COLORMAP_ADD / TEX_ALPHAMAP_ADD | ShaderNodeMixRGB(ADD) / ShaderNodeMath(ADD) | output = previous + layer |
| SUBTRACT | TEX_COLORMAP_SUB / TEX_ALPHAMAP_SUB | ShaderNodeMixRGB(SUBTRACT) / ShaderNodeMath(SUBTRACT) | output = previous - layer |
| MIX | TEX_COLORMAP_BLEND / TEX_ALPHAMAP_BLEND | ShaderNodeMixRGB(MIX, fac=blend_factor) | output = lerp(previous, layer, factor) |
| ALPHA_MASK | TEX_COLORMAP_ALPHA_MASK / TEX_ALPHAMAP_ALPHA_MASK | ShaderNodeMixRGB(MIX, fac=layer.alpha) | output = lerp(previous, layer, layer.alpha) |
| RGB_MASK | TEX_COLORMAP_RGB_MASK | ShaderNodeMixRGB(MIX, fac=layer.color) | output = lerp(previous, layer, layer.color) |

### ColorSource

| IR Value | DAT/HSD Constant | Blender Equivalent |
|----------|-------------------|--------------------|
| MATERIAL | RENDER_DIFFUSE_MAT (1<<0) / RENDER_ALPHA_MAT (1<<13) | ShaderNodeRGB with material diffuse color / ShaderNodeValue with material alpha |
| VERTEX | RENDER_DIFFUSE_VTX (2<<0) / RENDER_ALPHA_VTX (2<<13) | ShaderNodeAttribute('color_0') / ShaderNodeAttribute('alpha_0') |
| BOTH | RENDER_DIFFUSE_BOTH (3<<0) / RENDER_ALPHA_BOTH (3<<13) | Vertex attribute + material color via ShaderNodeMixRGB(ADD) / ShaderNodeMath(MULTIPLY) |

### LightingModel

| IR Value | DAT/HSD Constant | Blender Equivalent |
|----------|-------------------|--------------------|
| LIT | RENDER_DIFFUSE (1<<2) set | ShaderNodeBsdfPrincipled (color → Base Color) |
| UNLIT | RENDER_DIFFUSE (1<<2) unset | ShaderNodeEmission + ShaderNodeAddShader |

### LightmapChannel

| IR Value | DAT/HSD Constant | Blender Equivalent |
|----------|-------------------|--------------------|
| NONE | 0 (no lightmap flags set) | Treated as DIFFUSE |
| DIFFUSE | TEX_LIGHTMAP_DIFFUSE (1<<4) | Applied to base color chain |
| SPECULAR | TEX_LIGHTMAP_SPECULAR (1<<5) | Applied to specular chain |
| AMBIENT | TEX_LIGHTMAP_AMBIENT (1<<6) | Applied to base color chain |
| EXTENSION | TEX_LIGHTMAP_EXT (1<<7) | Applied to base color chain |
| SHADOW | TEX_LIGHTMAP_SHADOW (1<<8) | (not yet implemented) |

### CoordType

| IR Value | DAT/HSD Constant | Blender Equivalent |
|----------|-------------------|--------------------|
| UV | TEX_COORD_UV (0) | ShaderNodeUVMap (uv_map='uvtex_N') |
| REFLECTION | TEX_COORD_REFLECTION (1) | ShaderNodeTexCoord outputs[6] (Reflection) |
| SPECULAR_HIGHLIGHT | TEX_COORD_HILIGHT (2) | (not yet implemented) |
| SHADOW | TEX_COORD_SHADOW (3) | (not yet implemented) |
| CEL_SHADING | TEX_COORD_TOON (4) | (not yet implemented) |
| GRADATION | TEX_COORD_GRADATION (5) | (not yet implemented) |

### WrapMode

| IR Value | DAT/HSD Constant | Blender Equivalent |
|----------|-------------------|--------------------|
| CLAMP | GX_CLAMP (0) | tex_node.extension = 'EXTEND' |
| REPEAT | GX_REPEAT (1) | tex_node.extension = 'REPEAT' |
| MIRROR | GX_MIRROR (2) | tex_node.extension = 'REPEAT' (with mirror logic) |

### TextureInterpolation

| IR Value | DAT/HSD Constant | Blender Equivalent |
|----------|-------------------|--------------------|
| CLOSEST | GX_NEAR (0), GX_NEAR_MIP_NEAR (2), GX_NEAR_MIP_LIN (4) | tex_node.interpolation = 'Closest' |
| LINEAR | GX_LINEAR (1), GX_LIN_MIP_NEAR (3) | tex_node.interpolation = 'Linear' |
| CUBIC | GX_LIN_MIP_LIN (5) | tex_node.interpolation = 'Cubic' |

### CombinerInputSource

| IR Value | DAT/HSD Color Constants | DAT/HSD Alpha Constants | Blender Equivalent |
|----------|-------------------------|-------------------------|--------------------|
| ZERO | GX_CC_ZERO (15) | GX_CA_ZERO (7) | ShaderNodeRGB [0,0,0,1] / ShaderNodeValue 0.0 |
| ONE | GX_CC_ONE (12) | — | ShaderNodeRGB [1,1,1,1] |
| HALF | GX_CC_HALF (13) | — | ShaderNodeRGB [0.5,0.5,0.5,1] |
| TEXTURE_COLOR | GX_CC_TEXC (8) | — | texture_node.outputs[0] |
| TEXTURE_ALPHA | GX_CC_TEXA (9) | GX_CA_TEXA (4) | texture_node.outputs[1] |
| CONSTANT | TOBJ_TEV_CC_KONST_RGB/RRR/GGG/BBB/AAA (0x80-0x84) | TOBJ_TEV_CA_KONST_R/G/B/A (0x40-0x43) | ShaderNodeRGB/Value with resolved constant |
| REGISTER_0 | TOBJ_TEV_CC_TEX0_RGB/AAA (0x85-0x86) | TOBJ_TEV_CA_TEX0_A (0x44) | ShaderNodeRGB/Value with register 0 value |
| REGISTER_1 | TOBJ_TEV_CC_TEX1_RGB/AAA (0x87-0x88) | TOBJ_TEV_CA_TEX1_A (0x45) | ShaderNodeRGB/Value with register 1 value |

### CombinerOp

| IR Value | DAT/HSD Constant | Blender Equivalent |
|----------|-------------------|--------------------|
| ADD | GX_TEV_ADD (0) | lerp(A,B,C) + D via ShaderNodeMixRGB chain |
| SUBTRACT | GX_TEV_SUB (1) | D - lerp(A,B,C) via ShaderNodeMixRGB chain |
| COMPARE_R8_GT | GX_TEV_COMP_R8_GT (8) | (stubbed — returns input A) |
| COMPARE_R8_EQ | GX_TEV_COMP_R8_EQ (9) | (stubbed) |
| COMPARE_GR16_GT | GX_TEV_COMP_GR16_GT (10) | (stubbed) |
| COMPARE_GR16_EQ | GX_TEV_COMP_GR16_EQ (11) | (stubbed) |
| COMPARE_BGR24_GT | GX_TEV_COMP_BGR24_GT (12) | (stubbed) |
| COMPARE_BGR24_EQ | GX_TEV_COMP_BGR24_EQ (13) | (stubbed) |
| COMPARE_RGB8_GT | GX_TEV_COMP_RGB8_GT (14) / GX_TEV_COMP_A8_GT | (stubbed) |
| COMPARE_RGB8_EQ | GX_TEV_COMP_RGB8_EQ (15) / GX_TEV_COMP_A8_EQ | (stubbed) |

### CombinerBias

| IR Value | DAT/HSD Constant | Blender Equivalent |
|----------|-------------------|--------------------|
| ZERO | GX_TB_ZERO (0) | No bias applied |
| PLUS_HALF | GX_TB_ADDHALF (1) | ShaderNodeMixRGB(ADD) + [0.5, 0.5, 0.5, 1] |
| MINUS_HALF | GX_TB_SUBHALF (2) | ShaderNodeMixRGB(SUBTRACT) + [0.5, 0.5, 0.5, 1] |

### CombinerScale

| IR Value | DAT/HSD Constant | Blender Equivalent |
|----------|-------------------|--------------------|
| SCALE_1 | GX_CS_SCALE_1 (0) | ShaderNodeMixRGB(MULTIPLY) × [1,1,1,1] |
| SCALE_2 | GX_CS_SCALE_2 (1) | ShaderNodeMixRGB(MULTIPLY) × [2,2,2,2] |
| SCALE_4 | GX_CS_SCALE_4 (2) | ShaderNodeMixRGB(MULTIPLY) × [4,4,4,4] |
| SCALE_HALF | GX_CS_DIVIDE_2 (3) | ShaderNodeMixRGB(MULTIPLY) × [0.5,0.5,0.5,0.5] |

### OutputBlendEffect

| IR Value | DAT/HSD Constants (type, src, dst) | Blender Equivalent |
|----------|------------------------------------|--------------------|
| OPAQUE | GX_BM_NONE; or BLEND+ONE+ZERO; or LOGIC+COPY | No blend_method change (default opaque) |
| ALPHA_BLEND | GX_BM_BLEND + GX_BL_SRCALPHA + GX_BL_INVSRCALPHA | blend_method='HASHED' |
| INVERSE_ALPHA_BLEND | GX_BM_BLEND + GX_BL_INVSRCALPHA + GX_BL_SRCALPHA | blend_method='HASHED' + invert alpha via ShaderNodeMath(SUBTRACT) |
| ADDITIVE | GX_BM_BLEND + GX_BL_ONE + GX_BL_ONE | blend_method='BLEND' + ShaderNodeEmission + ShaderNodeAddShader + ShaderNodeBsdfTransparent |
| ADDITIVE_ALPHA | GX_BM_BLEND + GX_BL_SRCALPHA + GX_BL_ONE | blend_method='BLEND' + emission + alpha pre-multiply |
| ADDITIVE_INV_ALPHA | GX_BM_BLEND + GX_BL_INVSRCALPHA + GX_BL_ONE | blend_method='BLEND' + emission + inverse alpha pre-multiply |
| MULTIPLY | GX_BM_BLEND + GX_BL_DSTCLR + GX_BL_ZERO | blend_method='BLEND' + ShaderNodeBsdfTransparent with color input |
| SRC_ALPHA_ONLY | GX_BM_BLEND + GX_BL_SRCALPHA + GX_BL_ZERO | ShaderNodeMixRGB(MIX) by alpha with black |
| INV_SRC_ALPHA_ONLY | GX_BM_BLEND + GX_BL_INVSRCALPHA + GX_BL_ZERO | ShaderNodeMixRGB(MIX) by alpha (inverted) with black |
| INVISIBLE | GX_BM_BLEND + GX_BL_ZERO + GX_BL_ONE; or LOGIC+NOOP | blend_method='HASHED' + ShaderNodeValue(0) as alpha |
| BLACK | GX_BM_BLEND + GX_BL_ZERO + GX_BL_ZERO; or LOGIC+CLEAR | ShaderNodeRGB [0,0,0,1] as color |
| WHITE | GX_BM_LOGIC + GX_LO_SET | ShaderNodeRGB [1,1,1,1] as color |
| INVERT | GX_BM_LOGIC + GX_LO_INVCOPY | ShaderNodeInvert on color |
| CUSTOM | Any other combination | Raw source_factor/dest_factor preserved |

### BlendFactor

| IR Value | DAT/HSD Constant | Description |
|----------|-------------------|-------------|
| ZERO | GX_BL_ZERO (0) | Factor = 0 |
| ONE | GX_BL_ONE (1) | Factor = 1 |
| SRC_COLOR | GX_BL_SRCCLR (2) / GX_BL_DSTCLR | Factor = source or dest color |
| INV_SRC_COLOR | GX_BL_INVSRCCLR (3) / GX_BL_INVDSTCLR | Factor = 1 - source/dest color |
| SRC_ALPHA | GX_BL_SRCALPHA (4) | Factor = source alpha |
| INV_SRC_ALPHA | GX_BL_INVSRCALPHA (5) | Factor = 1 - source alpha |
| DST_ALPHA | GX_BL_DSTALPHA (6) | Factor = dest alpha |
| INV_DST_ALPHA | GX_BL_INVDSTALPHA (7) | Factor = 1 - dest alpha |

### SkinType

| IR Value | DAT/HSD Constant | Blender Equivalent |
|----------|-------------------|--------------------|
| WEIGHTED | POBJ_ENVELOPE (2<<12) | Vertex groups with per-bone weights + Armature modifier |
| SINGLE_BONE | POBJ_SKIN (0<<12) | Two vertex groups at 50/50 weight |
| RIGID | (no POBJ flag, property=None) | Single vertex group at 100% weight + matrix_local |

### LightType

| IR Value | DAT/HSD Constant | Blender Equivalent |
|----------|-------------------|--------------------|
| SUN | LOBJ_INFINITE (1<<0) | bpy.data.lights.new(type='SUN') |
| POINT | LOBJ_POINT (2<<0) | bpy.data.lights.new(type='POINT') |
| SPOT | LOBJ_SPOT (3<<0) | bpy.data.lights.new(type='SPOT') |

### Interpolation

| IR Value | DAT/HSD Constant | Blender Equivalent |
|----------|-------------------|--------------------|
| CONSTANT | HSD_A_OP_CON (1) | keyframe.interpolation = 'CONSTANT' |
| LINEAR | HSD_A_OP_LIN (2) | keyframe.interpolation = 'LINEAR' |
| BEZIER | HSD_A_OP_SPL/SPL0/SLP/KEY (3-6) | keyframe.interpolation = 'BEZIER' + handle values |

### ScaleInheritance

| IR Value | DAT/HSD Constant | Blender Equivalent |
|----------|-------------------|--------------------|
| ALIGNED | (default for all bones in this format) | bone.inherit_scale = 'ALIGNED' |
