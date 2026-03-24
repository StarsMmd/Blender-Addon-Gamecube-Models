# Intermediate Representation (IR) Specification

The IR is the output of Phase 4 (Scene Description) and the input to Phase 5A (Blender Build) and Phase 5B (Blend Export). It is a pure-Python dataclass hierarchy with no dependencies on `bpy` or the Node system.

**Design principles:**
- All types are `@dataclass` from the standard library
- All categorical values use Python `enum.Enum`
- No mutable shared state — each IR instance is a self-contained snapshot
- Fully serializable (JSON/YAML for debugging, pickle for caching)
- The IR is the intersection of DAT format features and Blender features
- Materials store abstract HSD parameters, not Blender shader node graphs

---

## File Organization

```
shared/IR/
  __init__.py             # re-exports all IR types
  enums.py                # all enum definitions
  scene.py                # IRScene (root)
  skeleton.py             # IRModel, IRBone
  geometry.py             # IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights, IRShapeKey
  material.py             # IRMaterial, IRTexture, IRImage, IRTextureTEV, IRPixelEngine
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
    HILIGHT = "HILIGHT"
    SHADOW = "SHADOW"
    TOON = "TOON"
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
    ENVELOPE = "ENVELOPE"    # Multi-bone weighted deformation
    SKIN = "SKIN"            # Single-bone deformation
    RIGID = "RIGID"          # Rigid attachment to one bone

class ScaleInheritance(Enum):
    """Bone scale inheritance mode."""
    ALIGNED = "ALIGNED"

class BlendMode(Enum):
    """Pixel engine blend mode."""
    NONE = "NONE"
    BLEND = "BLEND"
    LOGIC = "LOGIC"
    SUBTRACT = "SUBTRACT"

class ColormapOp(Enum):
    """Texture color blending operation."""
    NONE = "NONE"
    ALPHA_MASK = "ALPHA_MASK"
    RGB_MASK = "RGB_MASK"
    BLEND = "BLEND"
    MODULATE = "MODULATE"
    REPLACE = "REPLACE"
    PASS = "PASS"
    ADD = "ADD"
    SUB = "SUB"

class AlphamapOp(Enum):
    """Texture alpha blending operation."""
    NONE = "NONE"
    ALPHA_MASK = "ALPHA_MASK"
    BLEND = "BLEND"
    MODULATE = "MODULATE"
    REPLACE = "REPLACE"
    PASS = "PASS"
    ADD = "ADD"
    SUB = "SUB"
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
    """One armature with its geometry, materials, and animations."""
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
    # Coordinate system transform applied to the armature root
    coordinate_rotation: tuple[float, float, float]   # Euler XYZ radians (pi/2, 0, 0)

@dataclass
class IRBone:
    """One bone in a flat list. Parent relationship via index."""
    name: str
    parent_index: int | None                          # index into IRModel.bones, None for roots
    # Rest-pose transform (HSD values)
    position: tuple[float, float, float]
    rotation: tuple[float, float, float]              # Euler XYZ radians
    scale: tuple[float, float, float]
    inverse_bind_matrix: list[list[float]] | None     # 4x4 matrix or None
    # Flags
    flags: int                                        # raw HSD JOBJ_* flags
    is_hidden: bool
    inherit_scale: ScaleInheritance
    ik_shrink: bool                                   # shrink bone tail for IK compatibility
    # Pre-computed transforms (all 4x4 matrices stored as list[list[float]])
    world_matrix: list[list[float]]                   # accumulated world transform
    local_matrix: list[list[float]]                   # local SRT matrix
    edit_matrix: list[list[float]]                    # normalized world (for edit bone)
    local_edit_matrix: list[list[float]]              # normalized local (for edit bone)
    edit_scale_correction: list[list[float]]          # scale correction for animation baking
    accumulated_scale: tuple[float, float, float]     # parent-chain accumulated scale
    # Geometry binding
    mesh_indices: list[int]                           # indices into IRModel.meshes
    # Instancing
    instance_child_bone_index: int | None             # if JOBJ_INSTANCE, index of child to copy
```

---

## Geometry

**File:** `shared/IR/geometry.py`

```python
@dataclass
class IRMesh:
    """One draw call (PObject) with its material."""
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
    # For ENVELOPE: per-vertex bone assignments
    #   Each entry is (vertex_index, [(bone_name, weight), ...])
    assignments: list[tuple[int, list[tuple[str, float]]]] | None
    # For SKIN/RIGID: single bone name
    bone_name: str | None
    # Pre-computed deformed geometry (envelope transforms already applied)
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

Materials store **abstract HSD parameters**, not Blender shader node graphs. The shader node tree is a Blender-specific interpretation and is constructed in Phase 5A. This preserves full fidelity for round-trip export and keeps the IR Blender-independent.

```python
@dataclass
class IRMaterial:
    """Complete material specification from HSD parameters."""
    render_mode: int                                  # raw RENDER_* bit flags
    diffuse_color: tuple[float, float, float, float]  # linearized RGBA (0-1)
    ambient_color: tuple[float, float, float, float]
    specular_color: tuple[float, float, float, float]
    alpha: float                                      # material alpha (0-1)
    shininess: float
    textures: list[IRTexture]                         # ordered chain, enabled textures only
    pixel_engine: IRPixelEngine | None

@dataclass
class IRTexture:
    """One texture layer in a material's texture chain."""
    image: IRImage
    coord_type: CoordType                             # UV, REFLECTION, etc.
    uv_source: int                                    # UV layer index (source - 4 for GX)
    rotation: tuple[float, float, float]              # texture rotation XYZ
    scale: tuple[float, float, float]                 # texture scale
    translation: tuple[float, float, float]           # texture offset (UV space)
    wrap_s: WrapMode                                  # horizontal wrap
    wrap_t: WrapMode                                  # vertical wrap
    repeat_s: int                                     # horizontal repeat count
    repeat_t: int                                     # vertical repeat count
    flags: int                                        # raw TEX_* bit flags
    blending: float                                   # blend amount (0-1)
    interpolation: TextureInterpolation | None        # sampling filter
    tev: IRTextureTEV | None                          # TEV combiner config, if active
    colormap_op: ColormapOp                           # color blending operation
    alphamap_op: AlphamapOp                           # alpha blending operation
    lightmap_type: int                                # TEX_LIGHTMAP_* flags
    is_bump: bool                                     # TEX_BUMP flag

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
class IRTextureTEV:
    """TEV (Texture Environment) color combiner configuration."""
    color_op: int
    alpha_op: int
    color_bias: int
    alpha_bias: int
    color_scale: int
    alpha_scale: int
    color_clamp: int
    alpha_clamp: int
    color_inputs: tuple[int, int, int, int]           # TEV input selectors (a, b, c, d)
    alpha_inputs: tuple[int, int, int, int]
    konst: tuple[float, float, float, float]          # constant color RGBA (normalized)
    tev0: tuple[float, float, float, float]           # TEV register 0
    tev1: tuple[float, float, float, float]           # TEV register 1
    active: int                                       # TOBJ_TEVREG_ACTIVE_* flags

@dataclass
class IRPixelEngine:
    """Pixel Engine (PE) blend/alpha-test configuration."""
    blend_mode: BlendMode
    source_factor: int                                # GX blend factor
    destination_factor: int                           # GX blend factor
    logic_op: int                                     # GX logic operation
    z_comp: int                                       # depth compare function
    alpha_component_0: int                            # alpha compare reference 0
    alpha_op: int                                     # alpha compare operation
    alpha_component_1: int                            # alpha compare reference 1
```

---

## Animation

**File:** `shared/IR/animation.py`

All keyframes are fully decoded from the compressed HSD byte streams into explicit frame/value pairs. No further binary decoding is needed by Phase 5A.

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
    """One complete bone animation (corresponds to one Blender action)."""
    name: str
    tracks: list[IRBoneTrack]                         # one entry per animated bone
    loop: bool                                        # apply CYCLES modifier
    is_static: bool                                   # true if all channels are constant (pose)

@dataclass
class IRBoneTrack:
    """Baked animation data for one bone, in Blender local space."""
    bone_name: str
    # Each channel is a list of (frame, value) pairs, already converted to Blender space.
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
    texture_index: int                                # index into IRMaterial.textures
    translation_u: list[IRKeyframe] | None
    translation_v: list[IRKeyframe] | None
    scale_u: list[IRKeyframe] | None
    scale_v: list[IRKeyframe] | None
    rotation_x: list[IRKeyframe] | None
    rotation_y: list[IRKeyframe] | None
    rotation_z: list[IRKeyframe] | None

@dataclass
class IRShapeAnimationSet:
    """Shape key / morph target animation set."""
    name: str
    tracks: list[IRShapeTrack]

@dataclass
class IRShapeTrack:
    """Blend weight keyframes for one shape key."""
    bone_name: str                                    # bone whose mesh has shape keys
    keyframes: list[IRKeyframe]                       # blend weight per frame
```

---

## Constraints

**File:** `shared/IR/constraints.py`

Each constraint type has its own dataclass with explicitly typed fields.

```python
@dataclass
class IRIKConstraint:
    """Inverse Kinematics constraint."""
    bone_name: str                                    # bone to add constraint to
    chain_length: int                                 # number of bones in IK chain
    target_bone: str | None                           # IK target bone name
    pole_target_bone: str | None                      # pole target bone name
    pole_angle: float                                 # pole angle in radians
    bone_repositions: list[IRBoneReposition]           # head/tail adjustments for chain

@dataclass
class IRBoneReposition:
    """Bone head/tail offset applied during IK chain setup."""
    bone_name: str
    head_offset: tuple[float, float, float]
    tail_offset: tuple[float, float, float]

@dataclass
class IRCopyLocationConstraint:
    """Copy Location constraint (position tracking)."""
    bone_name: str
    target_bone: str
    influence: float                                  # 0.0 - 1.0

@dataclass
class IRTrackToConstraint:
    """Track To constraint (direction/aim)."""
    bone_name: str
    target_bone: str
    track_axis: str                                   # e.g. 'TRACK_X'
    up_axis: str                                      # e.g. 'UP_Y'

@dataclass
class IRCopyRotationConstraint:
    """Copy Rotation constraint."""
    bone_name: str
    target_bone: str
    owner_space: str                                  # 'WORLD' or 'LOCAL'
    target_space: str                                 # 'WORLD' or 'LOCAL'

@dataclass
class IRLimitConstraint:
    """Rotation or translation limit constraint. Used for both
    LIMIT_ROTATION and LIMIT_LOCATION — the parent list on IRModel
    determines which type."""
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
    coordinate_rotation: tuple[float, float, float]   # Euler XYZ for coord system fix
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

Pure-data replacement for `Frame.read_fobjdesc()`. Takes the compressed HSD keyframe byte buffer and returns `list[IRKeyframe]` without touching any bpy APIs. Supports all HSD interpolation types (CON, LIN, SPL0, SPL, SLP, KEY) and all value encoding formats (FLOAT, S16, U16, S8, U8).
