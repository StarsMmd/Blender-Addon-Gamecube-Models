# Implementation Notes

Cross-cutting findings, assumptions, and limitations of the plugin that aren't obvious from the code alone. This is the canonical home for empirical test results, reverse-engineered runtime invariants, and policies that required in-game verification to pin down. Current work-in-progress and session-specific debugging live elsewhere — only durable knowledge belongs here.

## Architecture

### Plan phase (IR → BR → build)

The import pipeline inserts a **Plan** phase (`importer/phases/plan/`) between `describe` (which produces a platform-agnostic IR) and `build_blender` (which consumes a Blender-specialised BR). See the full dataclass reference in [br_specification.md](br_specification.md).

Why this split exists: `build_blender` used to entangle two concerns — deciding how an IR concept maps onto Blender (inherit_scale mode, shader node graph shape, per-frame pose-basis formula, sRGB→linear, FOV→lens, Y-up→Z-up, etc.) and then calling bpy APIs to realise those decisions. The decisions were impossible to unit-test because every code path hit `nodes.new()` or `bpy.data.*` within the first few lines. Splitting the decision logic into Plan (pure, no bpy) with a BR dataclass output that build walks mechanically makes every decision testable with an in-memory fixture, and collapses the largest file in the importer (`build_blender/helpers/materials.py`) from ~900 lines to ~95.

Invariants enforced:
- `shared/BR/` holds plain data — tuples, lists, enum strings, 4x4 matrix lists. No bpy types, no mathutils.
- `importer/phases/plan/` has zero `bpy` imports.
- `importer/phases/build_blender/` has zero `IR` imports on the planned path. Build phase reads from BR only.
- `BR` must not import from `IR` — BR is downstream data, not a type alias.

Per-stage migration summary (all landed on `stars/WIP`):
- **Armature** — `BRArmature`, `BRBone`; Plan picks `inherit_scale='ALIGNED'` vs `'NONE'` from `accumulated_scale` uniformity.
- **Meshes** — `BRMesh`, `BRVertexGroup`, `BRMeshInstance`; flattens IR's three SkinType variants; expands `JOBJ_INSTANCE` bones into per-mesh instance entries.
- **Actions** — `BRAction`, `BRBoneTrack`, `BRBakeContext`; `compute_pose_basis` is pure (aligned edit-scale sandwich vs direct SRT delta).
- **Materials** — `BRMaterial`, `BRNodeGraph`, `BRNode`, `BRLink`, `BRImage`; full TEV / pixel-engine / output-shader wiring as graph data. `BRGraphBuilder` accumulates nodes; build walks the finalised graph.
- **Lights/cameras/constraints/particles** — `BRLight`, `BRCamera`, `BRCameraAnimation`, `BRConstraints`, `BRParticleSummary`. sRGB→linear, FOV→lens, and coord conversions all Plan-side. Constraints and particle summaries are pass-through wrappers (IR shapes already match Blender's API).

What still goes through IR:
- `post_process/` reads IR indirectly via the armature's custom properties. It's outside the purity contract (it mutates Blender state) and remains on IR.
- Material-animation helpers (`build_blender/helpers/material_animations.py`) still receive IR-typed keyframes as pass-through data. The `kf.interpolation.value` strings happen to be Blender's own enum values, so no conversion is needed at the bpy boundary.
- The exporter side is still Blender → IR directly via `describe_blender` — the symmetric `inspect_blender` (Blender → BR) and `un_plan` (BR → IR) counterparts are not yet written. Until they land, the BR-bounded round-trip tests in `tests/test_plan_round_trips.py` stay skipped.

## Render pipeline

### Render pass dispatch
The XD runtime runs **two** render passes per model during every scene render, including battle:

- **Pass 0 (opaque):** `HSD_JObjDispAll(mask=0x1)` — matches bones whose flags include `JOBJ_OPA` (bit 18, `0x40000`).
- **Pass 1 (translucent):** `HSD_JObjDispAll(mask=0x6)` — matches bones whose flags include `JOBJ_XLU` (bit 19) or `JOBJ_TEXEDGE` (bit 20).

A JObj whose transparency-flag bits are all zero renders in **neither pass** — its PObjects are invisible. `JOBJ_ROOT_OPA` / `JOBJ_ROOT_XLU` / `JOBJ_ROOT_TEXEDGE` (bits 28/29/30) propagate up the bone hierarchy and gate whether the pass dispatcher descends into a subtree at all.

The call chain for a given frame is `Prerender → PrerenderPass(0) → PrerenderPass(1) → GSgfxRenderModuleDoRender → _modelRender → _modelRenderModelSub → HSD_JObjDispAll`, all invoked unconditionally regardless of scene type. The battle camera and summary camera differ, but the render path does not.

### Material translucency is unsupported
The runtime supports translucent rendering in principle (see above), and a handful of shipped game PKXs do set `JOBJ_XLU` or `JOBJ_TEXEDGE` on individual bones. In practice, every material we flagged into the translucent pass rendered as fully invisible in-game — including on reference files that had previously been exported from an earlier version of this plugin. Flipping the same materials back to opaque restored visibility immediately.

Something beyond the JObj flag is required to complete the XLU-pass pipeline successfully, and we don't yet know what. Until somebody identifies the missing ingredient, **the exporter treats material translucency as unsupported**:

- Every `IRMaterial` ships with `is_translucent = False` regardless of the Blender BSDF `Alpha` slider or any sub-1.0 texel alpha.
- `_refine_bone_flags` always sets `JOBJ_OPA` / `JOBJ_ROOT_OPA` on mesh-owning bones and never sets the XLU bits.
- Image alpha data is still encoded into the exported texture (so alpha-test cutouts in textures survive the round-trip), but the **material** around those textures always renders as a fully opaque surface.

### PObject count ceiling
The runtime crashes on battle load somewhere around **240 PObjects per model**. The trigger is matrix-palette pool exhaustion: each PObject's 10-entry palette allocates from a fixed-size runtime pool via `HSD_ObjAlloc`; when the pool fills, `HSD_ObjAlloc` returns NULL and the next dereference reads garbage. Reference data:

- 236 PObjects — loads and plays in battle.
- 247-271 PObjects — crashes reliably on send-out.
- The exact threshold is not pinned down to the PObject; the useful rule is "keep well under 240."

The prep script's default `join_armature_child_meshes` step typically keeps a GLB/FBX-rip export under 200 PObjects, but models with exceptionally high per-vertex weight diversity may still need aggressive k-means palette clustering of weight tuples to drop the count further.

### Game render pipeline hardware limits
Invariants confirmed from the XD disassembly at `text1/` that the exporter and `pre_process` must respect. Violating any of these produces silent garbage (release build) or an assert trap (debug build) in-game; the importer tolerates them, so round-trip tests won't flag violations.

| Limit | Value | Enforced by |
|---|---|---|
| Matrix-palette entries per PObject | ≤ **10** | `HSD_Index2PosNrmMtx` asserts `r3 ≤ 9` |
| `GX_VA_PNMTXIDX` byte per palette slot | must be `slot × 3` ∈ {0, 3, …, 27} | same |
| Palette index actually referenced by DL | must be `< palette_size_for_this_PObject` | `SetupEnvelopeModelMtx` iterates 0..N-1 only |
| `sub_anim_count` per AnimMetadataEntry | ≤ **8** (`_MAX_SUB_ANIMS`) | PKX header writer |
| `anim_index` / `anim_index_ref` | must land inside `animated_joints[]` | `GSmodelSetAnimIndex` null-checks the entry but not the index |
| Envelope joint IBM | non-NULL when referenced by any envelope entry | `SetupEnvelopeModelMtx` asserts `r0 ≠ 0` |
| Matrix-pool allocation failure | returns NULL, next deref is garbage | `HSD_ObjAlloc` when pool full |
| `display_list_chunk_count` | `ushort` (≤ 65,535 × 32 bytes ≈ 2 MB) | PObject field size |

The 10-palette cap is by far the most commonly encountered — see "PObject count ceiling" above.

## Animation pipeline

### Rotation format
Runtime matrix composition from `HSD_MtxSRT` is:

    local = T · Rz · Ry · Rx · Sz · Sy · Sx

That's Euler **XYZ** order (X applied first). There is no quaternion track type in the runtime — the AObj dispatcher only recognises separate `HSD_A_J_ROTX / ROTY / ROTZ` opcodes (values 1 / 2 / 3). Location and scale have matching `_TRAX / _TRAY / _TRAZ` (5 / 6 / 7) and `_SCAX / _SCAY / _SCAZ` (8 / 9 / 10) opcodes.

The exporter converts Blender quaternion fcurves to Euler XYZ on the way out, which matches the runtime convention. A rotation-semantics diagnostic confirms that forward-running our exported Euler values through the runtime's `T · Rz · Ry · Rx · S` formula reproduces Blender's pose-bone local matrix to within float precision (≈ 1 μ).

### Round-trip test scope
A clean round-trip test validates only that `import ⟷ export` is its own inverse — it does not validate that the exported data means the same thing to the in-game runtime as it does to the importer. If the importer and exporter share an assumption that turns out to be wrong at runtime, a byte-clean round-trip coexists happily with a broken in-game render. Trust an in-game smoke test above the round-trip score.

### Scale inheritance (open bug)
Runtime scale composition in `HSD_MtxSRT` multiplies child positions by per-axis ratios of accumulated parent scale. When a bone chain has non-uniform parent scale, the per-axis ratios diverge from Blender's matrix-space evaluation, producing cascading errors that grow with chain depth. Pose-at-rest is unaffected; the error only appears once animation moves a bone within such a chain.

Mitigation is partial: Phase 5 uses a hybrid strategy that uses `inherit_scale='ALIGNED'` for uniform-scale chains and a direct SRT delta + `inherit_scale='NONE'` for non-uniform ones. The per-bone decision is driven by the uniformity of `IRBone.accumulated_scale` (threshold: `mx / mn < 1.1`, or `mn < 1e-3`).

### Near-zero-rest-scale rebind
Some rigs (bird wings, effect-themed appendages, pop-in/out helpers) have bones whose rest scale is effectively zero on one or more axes — the "hidden" state at rest — with animation keyframes toggling them to a visible scale at runtime. These bones cause three distinct numerical problems when imported directly:

1. **Mesh skinning instability.** `bone.rest_world.inverted()` has columns of magnitude `1/ε` on the tiny axes; any float noise in the pose matrix gets amplified by that factor into vertex positions.
2. **Animation basis explosion.** `basis = rest_local.inverted() @ animated_local` produces huge entries along tiny axes, then gets stored in F-curves at low precision.
3. **Descendant aligned-scale-correction blowup.** `compile_srt_matrix`'s aligned-scale correction is `mtx[i][j] *= parent_scl[j] / parent_scl[i]`. When `parent_scl` has a tiny component, off-diagonal entries of the descendant's `local_matrix` acquire factors of `1/ε` — in one real case (subame Bone_076) this produced a world-column magnitude of 44,000 for a bone whose rest scale was `(1.2, 0.55, 1.0)`.

The importer resolves all three with a rebind pass (`fix_near_zero_bone_matrices` in `importer/phases/describe/helpers/bones.py`):

- **Model-wide visible-scale aggregation.** For each near-zero bone, take the per-channel maximum absolute scale value observed across *every* animation's keyframes. If no animation reveals a visible value for a given channel, fall back to ±1.0 (sign preserved from the original rest). Computed by `compute_model_visible_scales`; deliberately not per-animation, because an animation that keeps the bone hidden throughout would otherwise leave its `rest_local_matrix` unstable. Taking max rather than first-non-tiny ensures basis values stay in `[0, 1]` range.
- **Full top-down transform recomputation** for the near-zero bone *and all transitive descendants*. Rebuilds `local_matrix`, `world_matrix`, `normalized_world_matrix`, `normalized_local_matrix`, `scale_correction`, and `accumulated_scale` through the shared `_compose_bone_transforms` helper, passing the rebound parent's accumulated scale as `parent_scl` so the aligned-scale correction uses stable denominators. Cascading world recomputation alone is insufficient — if the descendants' `local_matrix` still encodes the `1/ε` correction terms, `world = rebound_parent @ huge_local` stays huge. All six derived fields have to stay consistent because the animation baker (`build_blender/helpers/animations.py`) reads `normalized_local_matrix` and `scale_correction` as `local_edit` and `edit_sc` in its pose-basis formula.
- **Per-track `rest_local_matrix` rewrite.** Every `IRBoneTrack` for a rebound bone gets its `rest_local_matrix` rebuilt against the model-wide visible scale, including tracks whose own animation keeps the bone hidden. This ensures `basis = rest_local.inv() @ animated_local` is stable for all animations.
- **Pipeline order: rebind before mesh baking.** `describe_meshes` transforms vertices into world space using `IRBone.world_matrix`, so it runs *after* `fix_near_zero_bone_matrices` (not before). Running it first leaves mesh verts in the pre-rebind frame while bones move to the post-rebind frame — skinning silently breaks because verts and bones disagree on the rest world.

The rebind preserves GX semantics under forward pose evaluation: at a hidden frame, `animated_scale ≈ 0`, so `basis ≈ 0`, so `world = rebound_rest @ basis ≈ 0` — descendants collapse naturally via the basis rather than through the rest. At a visible frame, `basis ≈ 1` and world matches the GX-evaluated visible pose. Edit mode shows the bone at its rebound "visible" size rather than collapsed at the origin, which is a deliberate side effect: collapsed rest bones are unreadable in the rig outliner.

Deeply-nested ornamental chains (tentacles, feelers) where the non-uniformity is carried by a non-tiny rest scale — i.e. not rescuable by this rebind — are the remaining failure case for the underlying scale-inheritance bug.

### Animation timing crash
The game's battle state machine reads `timing_1..4` on each PKX anim slot to pace state transitions. A slot with a real active action but `timing_1 = 0` triggers a divide-by-zero modulo in the idle-loop code that advances through entry states without pausing, reliably crashing on send-out.

The `pre_process` phase rejects this configuration with a validator that fires before the binary is written.

## PKX metadata

### Body-map bone conventions
`anim_entries[i].body_map_bones[0..15]` is a per-slot lookup from body-part key to bone index. Slot indices 0-7 map to well-known body parts (root, head, center, body_3, neck, head_top, limb_a, limb_b); 8-15 are extended attachment points used by particle generators on effect-themed species.

Convention across the corpus:
- Pokémon models use **bone index 0** for unused slots (root fallback).
- Human NPC models use **-1** (which is -1 i32, 0xFFFFFFFF) for unused slots.

The two groups load through different in-game code paths. -1 is safe on the NPC path but dangerous for Pokémon slots — empirically, a Pokémon-slot PKX with -1 in unused body_map positions does not load cleanly, consistent with the game dereferencing `body_map_bones[slot]` as an unchecked bone index.

### Root bone index
The root bone used for animation is typically at **bone index 1**, not 0. Bone 0 is usually a static wrapper / pm-number node that holds the model's top-level transform but isn't itself animated. Body-map slot 0 (the "root" key) commonly points at index 1 in game models.

### Animation slot ordering
PKX anim slots reference animations by **DAT index**, not by action name. `anim_entries[i].sub_anims[0].anim_index = j` means slot `i` plays the `j`-th animation in the exported `animated_joints[]` list. If the exporter writes actions in alphabetical order but slot 0 expects a specific battle-idle action, slot 0 ends up playing whatever sorts first, producing the "all battle states look like slow walking" symptom.

The exporter enumerates actions in PKX slot order so `DAT[i]` matches the action assigned to slot `i`, with alphabetical fallback for armatures that have no PKX metadata. Empty slots are seeded with the first bone-animating action so every `anim_index` resolves deterministically.

## Material + texture

### HASHED blend method from imports
GLB/FBX rips frequently set `blend_method='HASHED'` on materials even when the corresponding texture is fully opaque (or opaque with only anti-aliased edge pixels). HASHED in Blender is stochastic alpha-to-coverage, which EEVEE uses to approximate alpha-blended materials without proper sorting. This is a display-only concession and doesn't imply the material was authored as translucent.

Consequence for the exporter: the decision whether a material is "translucent" should not be driven by `blend_method` alone. (And currently, it's not driven by anything — see "Material translucency is unsupported" above.)

### Texture alpha histogram semantics
When classifying a material's intended alpha behaviour, looking at the texture's alpha channel distribution matters more than the Blender shader setup. Three common patterns:

- **100% α=1.0** — fully opaque, no alpha data.
- **Bimodal (majority α=0 or α=1, little in between)** — alpha-test cutout (holes in geometry like iris ring). This should still export as an opaque material with texture alpha preserved so the in-game alpha-test can discard transparent texels.
- **Dominant α=1 with a small fringe (5-10%) of sub-1.0 values** — anti-aliased silhouette pixels on an otherwise opaque material. Not semantically translucent; should be ignored.

## Test infrastructure

### No game files in the repository
Test data is synthesised in-memory. Every unit test either constructs its fixtures with Python helpers that build valid node binaries, or uses `io.BytesIO` to simulate DAT streams. No `.pkx` / `.dat` files are committed.

### Round-trip test types
| Abbrev | Flow | Measures |
|---|---|---|
| BNB | bytes → parse → write → compare bytes | Binary-level fidelity (fuzzy word match) |
| NBN | parse → write → reparse → compare fields | Node field preservation through serialisation |
| NIN | parse → describe → compose → compare fields | IR round-trip fidelity |
| IBI | build → describe_blender → compare IR fields | Blender round-trip fidelity |
| BBB *(planned)* | plan → build → inspect_blender → compare BR fields | BR round-trip through bpy |
| IBI-via-Plan *(planned)* | plan → build → inspect_blender → un_plan → compare IR fields | Full import ⇄ export via BR on both sides |

NIN and IBI scores are computed against the full original data — not just the fields the exporter has implemented — so percentages naturally rise as more export features come online. The two planned test types are skipped placeholders in `tests/test_plan_round_trips.py` — they unblock once the exporter gains its `inspect_blender` (Blender → BR) and `un_plan` (BR → IR) phases.

### Blender Python version
Use `python3.11` for round-trip tests. The default `python3` on the dev machine is 3.10, which ships an older `bpy==3.4.0` that lacks APIs like `action.slots` that the current codebase requires. `python3.11` pairs with `bpy==4.5.7`.

## Exporter policies

### Matrix baking
The prep script bakes every armature's and child mesh's `matrix_world` into the geometry data before export. The exporter then rejects any armature or child mesh that still has a non-identity `matrix_world`, so the bone (decompose) and vertex (matmul) transform paths stay in the same reference frame.

A consequence worth knowing: `Armature.transform(world)` in Blender 4.5 applies rotation and scale correctly but silently drops the translation column on armatures. Rigs positioned off-origin in object mode need `bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)` (or manual repositioning to world origin) before the prep script runs, otherwise the mesh and skeleton end up in different frames.

### Armature-child-mesh auto-join
The prep script joins every armature-child mesh into one object before weight optimisation. Compose splits back out by material and by the 10-unique-weight-combo palette cap, so no data is lost. The point of joining is that each separate mesh object contributes at least one PObject per material slot regardless of vertex count — on a GLB rip that fragments the body into dozens of meshes, that alone can push the export past the 240 PObject crash ceiling.

Joining typically produces roughly one-third the PObject count of the same geometry exported as separate meshes, without any weight-handling changes.

### Weight optimisation
The prep script limits vertices to `MAX_WEIGHTS_PER_VERTEX = 3` influences (the hardware cap is 4) and quantises weights to 10% steps. Weight limiting and quantisation are the prep script's job; the compose phase only renormalises against floating-point drift so the Blender viewport preview of weights matches what ships to the DAT.

`pre_process._validate_vertex_weight_count` rejects any vertex with more than 4 non-zero weights as a backstop for rigs that bypass the prep script.

### Coordinate system
GameCube → Blender requires a π/2 rotation around the X-axis. Applied once at the armature level (`matrix_basis`). Never applied per-bone or per-mesh.

### Color space
The IR stores all colors in sRGB [0-1], normalised from u8 but not linearised. Blender-specific linearisation happens in Phase 5 only — material colors, material-animation RGB keyframes, and light colors are linearised when set on the corresponding Blender properties. Vertex colors are stored as `FLOAT_COLOR` (not `BYTE_COLOR`) so Blender does not auto-linearise them; the raw sRGB values pass through to the shader, matching the GameCube's gamma-space rendering. Image pixels are raw u8 RGBA and Blender handles color management internally.

## Convention: code comments vs. documentation

Code comments in `exporter/`, `importer/`, `shared/`, `scripts/`, `tools/` describe what the code does and why it's structured the way it is. They do **not**:

- Name specific model files (Pokémon species, asset filenames, etc.)
- Quote empirical measurements from in-game tests.
- Describe the debugging narrative that led to a fix.

Any such information belongs in `documentation/` (usually this file or `exporter_setup.md`). The rationale is that code comments age out faster than the code they annotate — a specific model that motivated a fix is rarely the right mental model for the next person encountering the code, and an empirical measurement gets stale the moment the code changes shape.
