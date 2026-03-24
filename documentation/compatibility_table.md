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
| Custom normals | ✅ | `IRMesh.normals` | ⚠️ Partial | ⚠️ | |
| Bone weights / envelopes | ✅ | `IRBoneWeights` | ✅ | ⚠️ | |
| Single-bone skinning | ✅ | `IRBoneWeights` | ✅ | ⚠️ | |
| Shape keys / morph targets | ✅ | `IRShapeKey` | ⚠️ Keys only, no anim | ❌ | |
| Bone instances (JOBJ_INSTANCE) | ✅ | `IRBone.instance_child` | ✅ | ❌ | |
| Spline curves | ✅ | via path animation | ⚠️ Path only | ❌ | |

## Materials

| Feature | DAT Parse (Phase 3) | IR Type (Phase 4) | Import (Phase 5A) | Export | Notes |
|---------|---------------------|--------------------|--------------------|--------|-------|
| Diffuse/alpha render modes | ✅ | `IRMaterial.render_mode` | ✅ | ❌ | |
| Material colors (diffuse) | ✅ | `IRMaterial.diffuse_color` | ✅ | ❌ | Linearized from sRGB |
| Material colors (ambient) | ✅ | `IRMaterial.ambient_color` | ❌ | ❌ | Parsed, not used in shader |
| Material colors (specular) | ✅ | `IRMaterial.specular_color` | ❌ | ❌ | Parsed, not used in shader |
| Texture mapping (UV) | ✅ | `IRTexture` with `CoordType.UV` | ✅ | ❌ | |
| Texture mapping (reflection) | ✅ | `IRTexture` with `CoordType.REFLECTION` | ⚠️ | ❌ | Partial |
| Texture colormap blend ops | ✅ | `ColormapOp` enum | ✅ | ❌ | |
| Texture alphamap blend ops | ✅ | `AlphamapOp` enum | ✅ | ❌ | |
| TEV color combiners (ADD/SUB) | ✅ | `IRTextureTEV` | ✅ | ❌ | |
| TEV comparison ops | ✅ | `IRTextureTEV` | ❌ | ❌ | Stubbed |
| Pixel engine (BLEND mode) | ✅ | `IRPixelEngine` | ✅ | ❌ | |
| Pixel engine (LOGIC mode) | ✅ | `IRPixelEngine` | ❌ | ❌ | Not implemented |
| Pixel engine (SUBTRACT) | ✅ | `IRPixelEngine` | ❌ | ❌ | Not implemented |
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
