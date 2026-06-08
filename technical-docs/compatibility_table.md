# DAT Feature Compatibility Table

This table tracks every feature in the HAL DAT `.dat` model format and its support status across the import/export pipeline phases.

**Legend:**
- ✅ Fully implemented
- ⚠️ Partially implemented (see notes)
- ❌ Not implemented
- — Not applicable

---

## Geometry

| Feature | DAT Parse (Phase 3) | IR Type (Phase 4) | Import (Phase 5) | Export | Notes |
|---------|---------------------|--------------------|--------------------|--------|-------|
| Skeleton / Bone hierarchy | ✅ | `IRBone` | ✅ | ✅ | Arbitrary armatures supported |
| Bone transforms (SRT) | ✅ | `IRBone` matrices | ✅ | ✅ | Armature object scale applied |
| Bone flags (hidden) | ✅ | `IRBone.is_hidden` | ✅ | ✅ | Reads `bone.hide` and auto-hides bones whose meshes are all hidden |
| Bone flags (billboard) | ✅ | `IRBone.flags` | ❌ | ❌ | Parsed but not applied |
| Meshes (tris, quads, tri-strips) | ✅ | `IRMesh` | ✅ | ✅ | Multi-material meshes split by material slot |
| UV coordinates (up to 8 layers) | ✅ | `IRUVLayer` | ✅ | ✅ | Per-material UV remapping on split |
| Vertex colors (CLR0, CLR1) | ✅ | `IRColorLayer` | ✅ | ⚠️ | |
| Custom normals | ✅ | `IRMesh.normals` | ✅ | ⚠️ | Normalized in describe phase |
| Bone weights / envelopes | ✅ | `IRBoneWeights` | ✅ | ✅ | Weights remapped when mesh is split. Game invariant: a mesh's owner joint (`JOBJ_ENVELOPE_MODEL`) must be disjoint from every envelope-weight deformer (`JOBJ_SKELETON` + IBM). Both prep scripts (`prepare_for_pkx_export.py`, `prepare_for_dat_export.py`) enforce this via `reparent_meshes_to_holder_bones` — for every mesh whose owner would otherwise be one of its own weighted bones, a coincident no-weight holder bone is inserted (parented to root, not to the deformer, so Blender's viewport doesn't double-evaluate the deformer's pose) and the mesh is bone-parented to it. Exporter's `pre_process` rejects any scene that still violates the invariant. |
| Single-bone skinning | ✅ | `IRBoneWeights` | ✅ | ✅ | Eyes, hair strands, and similar detached meshes: subject to the same owner-vs-deformer disjointness requirement (see row above). |
| Shape keys / morph targets | ⚠️ | `IRShapeKey` | ❌ | ❌ | Dataclass exists but never populated |
| Bone instances (JOBJ_INSTANCE) | ✅ | `IRBone.instance_child` | ✅ | ❌ | |
| Spline curves | ✅ | via path animation | ⚠️ Path only | ❌ | |

## Materials

| Feature | DAT Parse (Phase 3) | IR Type (Phase 4) | Import (Phase 5) | Export | Notes |
|---------|---------------------|--------------------|--------------------|--------|-------|
| Diffuse/alpha render modes | ✅ | `IRMaterial` (`color_source`, `alpha_source`, `lighting`, `is_translucent`) | ✅ | ✅ | Decomposed from render_mode bits |
| Material colors (diffuse) | ✅ | `IRMaterial.diffuse_color` | ✅ | ✅ | sRGB↔linear handled per color space strategy |
| Material colors (ambient) | ✅ | `IRMaterial.ambient_color` | ✅ (`dat_ambient_emission` node) | ✅ | Per-material emission node; `add_ambient_lighting.py` seeds defaults |
| Material colors (specular) | ✅ | `IRMaterial.specular_color` | ✅ | ✅ | Reverse-mapped from Principled BSDF Specular Tint |
| Texture mapping (UV) | ✅ | `IRTextureLayer` with `CoordType.UV` | ✅ | ✅ | |
| Texture mapping (reflection) | ✅ | `IRTextureLayer` with `CoordType.REFLECTION` | ⚠️ | ⚠️ | Partial on both sides |
| Texture colormap blend ops | ✅ | `LayerBlendMode` enum | ✅ | ✅ | |
| Texture alphamap blend ops | ✅ | `LayerBlendMode` enum | ✅ | ✅ | |
| TEV color combiners (ADD/SUB) | ✅ | `ColorCombiner` | ✅ | ✅ | |
| TEV comparison ops | ✅ | `ColorCombiner` | ❌ | ❌ | Stubbed |
| Pixel engine (BLEND mode) | ✅ | `FragmentBlending` | ✅ | ✅ | Includes HASHED fallback for translucent-no-blend |
| Pixel engine (LOGIC mode) | ✅ | `FragmentBlending` | ✅ | ✅ | Maps to BLACK/WHITE/INVERT/INVISIBLE/OPAQUE |
| Pixel engine (SUBTRACT) | ✅ | `FragmentBlending` | ⚠️ | ⚠️ | Maps to CUSTOM, best-effort in build |
| Image decoding (all GX formats) | ✅ | `IRImage` | ✅ | ✅ | All GX formats; auto-select or user override via `dat_gx_format` |

## Animations

| Feature | DAT Parse (Phase 3) | IR Type (Phase 4) | Import (Phase 5) | Export | Notes |
|---------|---------------------|--------------------|--------------------|--------|-------|
| Bone animation (SRT keyframes) | ✅ | `IRBoneAnimationSet` | ✅ | ✅ | Euler and quaternion rotation supported |
| Path animation (spline-based) | ✅ | `IRBoneTrack` | ✅ | ❌ | |
| Animation looping | ✅ | `.loop` flag | ✅ (CYCLES modifier) | ✅ | `_Loop` / `_loop` in action name |
| Multiple animation sets | ✅ | `list[IRBoneAnimationSet]` | ✅ | ✅ | All matching actions exported |
| Material color animation (RGB) | ✅ | `IRMaterialTrack` | ✅ (sRGB->linear) | ✅ | |
| Material alpha animation | ✅ | `IRMaterialTrack` | ✅ | ✅ | |
| Texture UV animation | ✅ | `IRTextureUVTrack` | ✅ | ✅ | Multi-frame eye-blink V-flip handled in compose |
| Texture image swap (TIMG) | ✅ Parsed | ❌ Not yet | ❌ | ❌ | Track type recognized, not decoded |
| Palette swap (TCLT) | ✅ Parsed | ❌ Not yet | ❌ | ❌ | Track type recognized, not decoded |
| Shape animation | ✅ Parsed | `IRShapeAnimationSet` | ❌ Stub | ❌ | Node classes exist, no build logic |
| Render animation (constraints) | ✅ Parsed | ❌ Not yet | ❌ | ❌ | Fields recently added |
| Light animation | ✅ Parsed | ❌ Stub | ❌ | ❌ | Node classes exist, no build logic |
| Camera animation | ✅ | `IRCameraAnimationSet` | ✅ | ✅ | Position, target, FOV, roll, near/far |

## Constraints

| Feature | DAT Parse (Phase 3) | IR Type (Phase 4) | Import (Phase 5) | Export | Notes |
|---------|---------------------|--------------------|--------------------|--------|-------|
| IK constraints | ✅ | `IRIKConstraint` | ✅ | ✅ | |
| Copy Location | ✅ | `IRCopyLocationConstraint` | ✅ | ✅ | Weighted multi-source |
| Track To (direction) | ✅ | `IRTrackToConstraint` | ✅ | ✅ | |
| Copy Rotation | ✅ | `IRCopyRotationConstraint` | ✅ | ✅ | |
| Rotation limits | ✅ | `IRLimitConstraint` | ✅ | ✅ | Per-axis min/max |
| Translation limits | ✅ | `IRLimitConstraint` | ✅ | ✅ | Per-axis min/max |

## Scene Objects

| Feature | DAT Parse (Phase 3) | IR Type (Phase 4) | Import (Phase 5) | Export | Notes |
|---------|---------------------|--------------------|--------------------|--------|-------|
| Lights (AMBIENT) | ✅ | `IRLight` (type=AMBIENT) | ✅ (no-op POINT, energy=0) | ✅ | Sorted first (LightSet[0]) on export |
| Lights (SUN) | ✅ | `IRLight` | ✅ | ✅ | |
| Lights (POINT) | ✅ | `IRLight` | ✅ | ✅ | |
| Lights (SPOT) | ✅ | `IRLight` | ✅ | ✅ | With target + TRACK_TO |
| Cameras (static) | ✅ | `IRCamera` | ✅ | ✅ | Position, FOV, clip, TRACK_TO target |
| Fog | ✅ Parsed | `IRFog` (stub) | ❌ | ❌ | No fog data found in tested models |
| Particles (GPT1) | ✅ | `IRParticleSystem` | ⚠️ Stub | ❌ Disabled | 15 models ship GPT1 data; parser, disassembler, IR, assembler, opcode specs all done and unit-tested. `build_particles` is a stub that only records generator/texture counts — the generator→bone binding mechanism has not been found (not in `JOBJ_PTCL`, `_particleJObjCallback`, PKX body map, WZX move files, common.rel indexes, or the nearby DOL data tables). `compose_particles` / `describe_particles` helpers remain available. |

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
