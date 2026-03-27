# DAT Feature Compatibility Table

This table tracks every feature in the GameCube SysDolphin `.dat` format and its support status across the import/export pipeline phases.

**Legend:**
- ✅ Fully implemented
- ⚠️ Partially implemented (see notes)
- ❌ Not implemented
- — Not applicable

---

## Geometry

| Feature | DAT Parse (Phase 3) | IR Type (Phase 4) | Import (Phase 5A) | Export | Notes |
|---------|---------------------|--------------------|--------------------|--------|-------|
| Skeleton / Bone hierarchy | ✅ | `IRBone` | ✅ | ⚠️ Round-trip only | |
| Bone transforms (SRT) | ✅ | `IRBone` matrices | ✅ | ⚠️ Round-trip only | |
| Bone flags (hidden) | ✅ | `IRBone.is_hidden` | ✅ | ❌ | |
| Bone flags (billboard) | ✅ | `IRBone.flags` | ❌ | ❌ | Parsed but not applied |
| Meshes (tris, quads, tri-strips) | ✅ | `IRMesh` | ✅ | ⚠️ Round-trip only | |
| UV coordinates (up to 8 layers) | ✅ | `IRUVLayer` | ✅ | ⚠️ | |
| Vertex colors (CLR0, CLR1) | ✅ | `IRColorLayer` | ✅ | ⚠️ | |
| Custom normals | ✅ | `IRMesh.normals` | ✅ | ⚠️ | Normalized in describe phase |
| Bone weights / envelopes | ✅ | `IRBoneWeights` | ✅ | ⚠️ | |
| Single-bone skinning | ✅ | `IRBoneWeights` | ✅ | ⚠️ | |
| Shape keys / morph targets | ⚠️ | `IRShapeKey` | ❌ | ❌ | Dataclass exists but never populated |
| Bone instances (JOBJ_INSTANCE) | ✅ | `IRBone.instance_child` | ✅ | ❌ | |
| Spline curves | ✅ | via path animation | ⚠️ Path only | ❌ | |

## Materials

| Feature | DAT Parse (Phase 3) | IR Type (Phase 4) | Import (Phase 5A) | Export | Notes |
|---------|---------------------|--------------------|--------------------|--------|-------|
| Diffuse/alpha render modes | ✅ | `IRMaterial` (`color_source`, `alpha_source`, `lighting`, `is_translucent`) | ✅ | ❌ | Decomposed from render_mode bits |
| Material colors (diffuse) | ✅ | `IRMaterial.diffuse_color` | ✅ | ❌ | Linearized from sRGB |
| Material colors (ambient) | ✅ | `IRMaterial.ambient_color` | ❌ | ❌ | Parsed, not used in shader |
| Material colors (specular) | ✅ | `IRMaterial.specular_color` | ❌ | ❌ | Parsed, not used in shader |
| Texture mapping (UV) | ✅ | `IRTextureLayer` with `CoordType.UV` | ✅ | ❌ | |
| Texture mapping (reflection) | ✅ | `IRTextureLayer` with `CoordType.REFLECTION` | ⚠️ | ❌ | Partial |
| Texture colormap blend ops | ✅ | `LayerBlendMode` enum | ✅ | ❌ | |
| Texture alphamap blend ops | ✅ | `LayerBlendMode` enum | ✅ | ❌ | |
| TEV color combiners (ADD/SUB) | ✅ | `ColorCombiner` | ✅ | ❌ | |
| TEV comparison ops | ✅ | `ColorCombiner` | ❌ | ❌ | Stubbed |
| Pixel engine (BLEND mode) | ✅ | `FragmentBlending` | ✅ | ❌ | |
| Pixel engine (LOGIC mode) | ✅ | `FragmentBlending` | ✅ | ❌ | Maps to BLACK/WHITE/INVERT/INVISIBLE/OPAQUE |
| Pixel engine (SUBTRACT) | ✅ | `FragmentBlending` | ⚠️ | ❌ | Maps to CUSTOM, best-effort in build |
| Image decoding (all GX formats) | ✅ | `IRImage` | ✅ | ⚠️ Round-trip only | |

## Animations

| Feature | DAT Parse (Phase 3) | IR Type (Phase 4) | Import (Phase 5A) | Export | Notes |
|---------|---------------------|--------------------|--------------------|--------|-------|
| Bone animation (SRT keyframes) | ✅ | `IRBoneAnimationSet` | ✅ | ❌ | |
| Path animation (spline-based) | ✅ | `IRBoneTrack` | ✅ | ❌ | |
| Animation looping | ✅ | `.loop` flag | ✅ (CYCLES modifier) | ❌ | |
| Multiple animation sets | ✅ | `list[IRBoneAnimationSet]` | ✅ | ❌ | |
| Material color animation (RGB) | ✅ | `IRMaterialTrack` | ✅ (sRGB->linear) | ❌ | |
| Material alpha animation | ✅ | `IRMaterialTrack` | ✅ | ❌ | |
| Texture UV animation | ✅ | `IRTextureUVTrack` | ✅ | ❌ | |
| Texture image swap (TIMG) | ✅ Parsed | ❌ Not yet | ❌ | ❌ | Track type recognized, not decoded |
| Palette swap (TCLT) | ✅ Parsed | ❌ Not yet | ❌ | ❌ | Track type recognized, not decoded |
| Shape animation | ✅ Parsed | `IRShapeAnimationSet` | ❌ Stub | ❌ | Node classes exist, no build logic |
| Render animation (constraints) | ✅ Parsed | ❌ Not yet | ❌ | ❌ | Fields recently added |
| Light animation | ✅ Parsed | ❌ Stub | ❌ | ❌ | Node classes exist, no build logic |
| Camera animation | ✅ Parsed | ❌ Stub | ❌ | ❌ | |

## Constraints

| Feature | DAT Parse (Phase 3) | IR Type (Phase 4) | Import (Phase 5A) | Export | Notes |
|---------|---------------------|--------------------|--------------------|--------|-------|
| IK constraints | ✅ | `IRIKConstraint` | ✅ | ❌ | |
| Copy Location | ✅ | `IRCopyLocationConstraint` | ✅ | ❌ | Weighted multi-source |
| Track To (direction) | ✅ | `IRTrackToConstraint` | ✅ | ❌ | |
| Copy Rotation | ✅ | `IRCopyRotationConstraint` | ✅ | ❌ | |
| Rotation limits | ✅ | `IRLimitConstraint` | ✅ | ❌ | Per-axis min/max |
| Translation limits | ✅ | `IRLimitConstraint` | ✅ | ❌ | Per-axis min/max |

## Scene Objects

| Feature | DAT Parse (Phase 3) | IR Type (Phase 4) | Import (Phase 5A) | Export | Notes |
|---------|---------------------|--------------------|--------------------|--------|-------|
| Lights (SUN) | ✅ | `IRLight` | ✅ | ❌ | |
| Lights (POINT) | ✅ | `IRLight` | ✅ | ❌ | |
| Lights (SPOT) | ✅ | `IRLight` | ✅ | ❌ | With target + TRACK_TO |
| Cameras | ✅ Parsed | `IRCamera` (stub) | ❌ | ❌ | |
| Fog | ✅ Parsed | `IRFog` (stub) | ❌ | ❌ | |
| Particles | ✅ Parsed | ❌ Not planned | ❌ | ❌ | |

## Keyframe Encoding

| Feature | DAT Parse (Phase 3) | IR Type (Phase 4) | Notes |
|---------|---------------------|--------------------|----|
| Constant interpolation (CON/KEY) | ✅ | `Interpolation.CONSTANT` | |
| Linear interpolation (LIN) | ✅ | `Interpolation.LINEAR` | |
| Bezier/spline interpolation (SPL/SPL0) | ✅ | `Interpolation.BEZIER` | With tangent handles |
| Slope-only (SLP) | ✅ | Used for tangent computation | |
| Float value encoding | ✅ | `IRKeyframe.value` | 32-bit float |
| S16/U16 value encoding | ✅ | `IRKeyframe.value` | Decoded to float |
| S8/U8 value encoding | ✅ | `IRKeyframe.value` | Decoded to float |

## Container Formats (Phase 1)

| Format | Detection | Extraction | Notes |
|--------|-----------|------------|-------|
| `.dat` / `.fdat` / `.rdat` | Extension | ✅ Pass-through | Raw DAT bytes |
| `.pkx` (Colosseum) | Extension | ✅ Strip 0x40 header | |
| `.pkx` (XD) | Extension | ✅ Strip 0xE60+ header | With optional GPT1 chunk |
| `.fsys` archive | Extension or `FSYS` magic | ✅ Multi-model extraction | LZSS decompression, filters to dat/mdat/pkx entries |
