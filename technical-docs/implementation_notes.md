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
- The exporter mirrors the import shape: `describe` (Blender → BR) and `plan` (BR → IR) live under `exporter/phases/`. Every domain — armature, meshes, materials, animations, lights, cameras, constraints — flows through real BR types end-to-end. Materials: describe serialises the Blender shader graph into a faithful BRNodeGraph; plan reads the graph via a `_GraphView` index and recovers IRMaterial fields (lighting model, texture layers, blend modes, image data). Animations: describe runs the bpy-side unbake + Bezier sparsifier (`animations_decode.py`) and packages the result into BRAction / BRBoneTrack / BRMaterialTrack; plan rebuilds the rest_local_matrix from rest SRT and emits IRBoneAnimationSet. The BR-bounded round-trip tests in `tests/test_plan_round_trips.py` stay skipped because they require a real bpy runtime — they're exercised via `tests/round_trip/run_round_trips.py`.

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
- `refine_bone_flags` (in `exporter/phases/plan/helpers/scene.py`) always sets `JOBJ_OPA` / `JOBJ_ROOT_OPA` on mesh-owning bones and never sets the XLU bits.
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

### Envelope-weight-1.0 IBM short-circuit

**Plain-English summary.** When you skin a vertex to a single bone at full strength, the game has a shortcut: instead of going through the full skinning math, it just sticks that vertex onto the bone directly. The shortcut skips one of the matrices (the "inverse bind matrix") that the full path would have used. Our exporter was always writing vertex positions assuming the full path would run. So when the game took the shortcut on a vertex weighted entirely to one bone, it skipped the matrix our exporter had compensated for — leaving a small leftover transform that pushed the vertex a few millimetres off where it should sit. This is invisible on game-original models because the original tooling knew about the shortcut and authored numbers that worked either way, and it's invisible on a re-import to Blender because the Blender side uses the full path for everyone with no shortcut. It only surfaces in-game on arbitrary models, and it's most visible on vertices that float clear of their neighbours (like an eye-area vertex on the body) because the offset has nothing nearby to hide behind.

**Technical detail.** `_modelParseLoadEnvelopeMatrix` in the XD disassembly contains a special-case branch that fires for envelopes whose first (and only) entry has weight ≥ 1.0:

```
lfs   f0, 0x8(r26)     # envelope[0].weight
fcmpo cr0, f0, f31     # compare to 1.0
cror  eq, gt, eq
bne   <multi-bone path>

# single-bone-weight=1 path:
cmplwi r27, 0x0        # is coord (the mesh's _HSD_mkEnvelopeModelNodeMtx result) NULL?
beq   <no-coord branch — output = joint.matrix, IBM NOT applied>
# coord branch:
output = joint.matrix @ joint.IBM   (coord is concatenated later)
```

So the runtime's per-envelope matrix is:

| Envelope shape | `coord` present | Matrix used |
|---|---|---|
| Multi-bone (Σwᵢ blend) | any | `Σ wᵢ · joint.matrix @ joint.IBM`, then `@ coord` if present |
| Single bone, weight = 1.0 | yes | `joint.matrix @ joint.IBM @ coord` |
| **Single bone, weight = 1.0** | **no (mesh hangs off `SKELETON_ROOT`)** | **`joint.matrix` — IBM is omitted entirely** |

`_undeform_vertices` in compose **must mirror this**: when the envelope has one bone at weight = 1.0 and the mesh's coord is None, encode the vertex as `inv(bone.world) @ vertex_world`, not the general `inv(Σ wᵢ · bone.world @ bone.IBM) @ vertex_world`. Otherwise the runtime decodes those single-bone vertices without their encoded IBM and they end up offset by `bone.world_at_bind @ bone.IBM` — close to identity at rest if (and only if) every bone-matrix reconstruction is perfectly bit-stable, but visibly off the moment any non-bit-exact factor enters the chain.

Round-trip game models hide this because their IBM/SRT bytes were authored by tooling that already accounted for the short-circuit. Arbitrary-rig exports surface it as small offsets on body-mesh vertices weighted exclusively to a single bone (face vertices weighted to `head`, hip vertices to `hips`, etc.), with the offset most visible relative to other parts of the same model — e.g. an eye mesh promoted to `SkinType.SINGLE_BONE` (rigid skin path, no envelope at all) sits exactly on the head while the body's head-area vertices drift a few millimetres.

The fix is local to `_undeform_vertices` — detect `len(weight_list) == 1 and weight ≈ 1.0 and coord is None` and skip the IBM term for that envelope-combo. No changes to the file format or to the runtime, and round-trip tests are untouched because round-tripped envelopes have always satisfied the runtime's expectation by construction.

### Mesh-owner / deformer disjoint invariant

Game-native models keep two joint roles strictly disjoint:

- a **mesh-owner** joint carries `JOBJ_ENVELOPE_MODEL` (a DObject hangs off it) and has **no** `JOBJ_SKELETON` flag and **no** inverse-bind matrix;
- a **deformer** joint carries `JOBJ_SKELETON` + an IBM (envelope weights target it) and owns **no** mesh.

Survey of 76 game-native PKX files: **0** weight a vertex to a mesh-owner joint, and **0** set `ENV_MODEL`+`SKELETON` on the same joint. The roles never overlap.

The export pipeline enforces the no-overlap-of-*flags* half itself — `refine_bone_flags` (`exporter/phases/plan/helpers/scene.py`) strips `JOBJ_SKELETON` from any bone that owns a mesh. But it can't enforce the no-*weighting*-to-an-owner half, because that's a question of scene topology, not flags. Arbitrary rips routinely violate it: a detached mesh weighted ~100% to a single bone (eyes, hair strands) is also *attached* to that bone, and a body mesh is typically owned by `hips` while also being weighted to it.

The failure mode is geometric. The envelope coordinate system (`_envelope_coord_system`, mirrored in describe and compose) resolves a mesh's coord from its owner bone by walking up to the nearest `JOBJ_SKELETON` ancestor. When the owner is *itself* the deformer but has had `SKELETON` stripped (because it owns the mesh), the walk overshoots to an ancestor and takes the third branch `(world[ancestor] @ ibm[owner]).inv @ world[owner]`, producing a coord that disagrees with what the runtime's `_HSD_mkEnvelopeModelNodeMtx` computes. The vertices render offset — visibly "floating" for a whole detached eye mesh (~9.7-unit offset measured on one rig), and as subtler whole-body distortion when the body's owner is a non-root deformer. It is invisible on round-trips (describe and compose mirror each other) and in Blender previews (full skin path for everyone), so it only surfaces in-game.

**Fix (prep-script, not in the IR):** `reparent_meshes_to_holder_bones` in `scripts/prepare_for_pkx_export.py`. For every mesh whose export owner bone (Blender bone-parent if set, else the nearest common ancestor of its weighted bones) is itself a deformer, it inserts a coincident no-weight **holder bone** as a child of that deformer and bone-parents the mesh to the holder. The exporter then sees owner = holder (`ENV_MODEL`, non-deformer → no `SKELETON`/IBM) and weights = the original deformer (`SKELETON`) — disjoint, exactly mirroring the structure the importer already round-trips cleanly.

Done in prep rather than as an IR transform deliberately: native `mesh.parent_bone` is already honored by describe (`_determine_parent_bone_name`) → plan, and `describe_armature` emits bones depth-first, so a holder added in Blender lands in the correct serialized (DFS) position and the PKX header's name→index body-map (resolved in describe from the final armature) stays correct — **no bone-index remapping, no header sync, no pipeline change**. `bake_transforms` was taught to skip bone-parented meshes (their geometry is baked to world space on the first pass while still object-parented), keeping the deploy's two-pass prep idempotent.

In-game confirmation (2026-06-07): resolved both the floating-eye issue and general body jankiness across six arbitrary PBR rips. An earlier attempt, `SkinType.SINGLE_BONE` promotion (commit 57bf5b9), was reverted — it sidestepped the envelope path for single-bone meshes but placed them wrong in a different way and didn't address bodies. Remaining: mirror the prep step into `scripts/prepare_for_dat_export.py` for `.dat` output.

## Animation pipeline

### Rotation format
Runtime matrix composition from `HSD_MtxSRT` is:

    local = T · Rz · Ry · Rx · Sz · Sy · Sx

That's Euler **XYZ** order (X applied first). There is no quaternion track type in the runtime — the AObj dispatcher only recognises separate `HSD_A_J_ROTX / ROTY / ROTZ` opcodes (values 1 / 2 / 3). Location and scale have matching `_TRAX / _TRAY / _TRAZ` (5 / 6 / 7) and `_SCAX / _SCAY / _SCAZ` (8 / 9 / 10) opcodes.

The exporter converts Blender quaternion fcurves to Euler XYZ on the way out, which matches the runtime convention. A rotation-semantics diagnostic confirms that forward-running our exported Euler values through the runtime's `T · Rz · Ry · Rx · S` formula reproduces Blender's pose-bone local matrix to within float precision (≈ 1 μ).

### Keyframe interpolation (Hermite tangents)
The runtime interpolates spline keyframes with a **cubic Hermite** using the tangents authored per keyframe in the FObj stream. Confirmed from the GXXE01 disassembly: `HSD_FObjInterpretAnim` (`text1/fobj/`) loads `(1/fterm, time, p0, p1, d0, d1)` and calls `splGetHelmite` (`text1/spline/splGetHelmite.s`), whose polynomial expands to the standard Hermite basis `p0·h00(u) + d0·Δ·h10(u) + p1·h01(u) + d1·Δ·h11(u)`, `u = time/Δ`. Linear keys use `p0 + ((p1−p0)/Δ)·time`. This matches HSDRaw's reference `FOBJ_Player` byte-for-byte.

**The bug (fixed):** the decoder reads the tangents into `IRKeyframe.slope_in/slope_out`, but for *bone* tracks they were never turned into Blender F-curve handles — `_insert_raw_keyframes` emitted `BEZIER` points and left Blender's default **AUTO_CLAMPED** handles to invent the in-between motion. The per-frame bake then sampled that wrong curve. Measured on absol's idle: at keyframes all curves agree, but **between** keyframes the imported motion led/lagged the true motion by **2–5° per segment** with the sign flipping segment-to-segment — i.e. the "wobble." (UV/material tracks were never affected; they already set handles.)

**The fix:** `_assign_bezier_handles` (`describe/helpers/animations.py`) converts each tangent into a bezier handle placed one third of the segment's frame span along the tangent — `handle = (frame ± Δ/3, value ± slope·Δ/3)`. Because the handles sit at 1/3 spacing the bezier's x-coordinate is linear in its parameter, so sampling at integer frames reproduces `splGetHelmite` exactly (verified end-to-end across all 82 of absol's animated rotation channels: max error **0.00004°**, was 5.13°). `build_blender/helpers/animations.py` must set `handle_{left,right}_type = 'FREE'` before writing the positions — AUTO/AUTO_CLAMPED handles are recomputed by Blender and would discard them. This also improves export round-trips: the bone exporter doesn't read these handles directly — it dense-samples the corrected curve at integer frames (`fc.evaluate`), unbakes each frame, and re-derives tangents by finite differences before a Hermite-bounded sparsification — so fixing the in-Blender curve tightens what those samples reproduce. (Only the material track path reads `keyframe_point.handle_{left,right}` directly; the bone unbake is nonlinear, so handle slopes can't transfer straight into HSD tangent space.)

Two subtleties worth remembering:

1. **Asymmetric tangents (SLP opcode).** A keyframe's incoming and outgoing tangents are usually equal (plain `SPL`/`SPL0`), but an `HSD_A_OP_SLP` opcode sits *between* two keys and overrides the **outgoing** tangent of the following segment without emitting a value. The decoder folds that override into the *next* key's `slope_in`. So the correct per-key mapping is: the segment **ending** at key `i` uses `keyframes[i].slope_out` (its incoming tangent), and the segment **leaving** key `i` uses `keyframes[i+1].slope_in` (its outgoing tangent). `_assign_bezier_handles` reads both, so the asymmetric case is handled — but it has only been *verified* against pure-SPL models (Colo/XD Pokémon don't appear to emit SLP). If a model that uses SLP surfaces and its tangents look wrong at SLP keys, re-check this mapping against `splGetHelmite` first.
2. **Segment-type convention is opposite to Blender's.** In the runtime a segment's interpolation is governed by the opcode of its **end** key (`op_intrp` is the type of the key whose frame you're approaching); in Blender a segment's interpolation is governed by the **start** key's `interpolation`. This is invisible on all-spline or all-linear channels (every segment is the same type), but on a channel that *mixes* linear and spline keys the type can land on the wrong segment at the boundary. Not currently corrected — fixing it means shifting the interpolation type by one key when building the F-curve, and needs a mixed-interpolation test model to validate.

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
`anim_entries[i].body_map_bones[0..15]` is a per-slot lookup from body-part key to bone index. The 16 slots are: `origin, mouth, chest, tail, eye_left, eye_right, hand_left, hand_right, additional_1, additional_2, additional_3, additional_4, foot_left, foot_right, center, additional_5`. Naming comes from a corpus + disassembly survey of which slots the waza-effect pipeline (`ParticleEntry / EffectEntry / ModelEntry / LensFlareEntry`) reads in practice: `origin` (slot 0) covers ~95% of attaches, `mouth` (slot 1) anchors head-attached Model entries (fire-breath models, status overlays), `chest` (slot 2) anchors LensFlare entries (chest-level light bursts), and the remaining slots are per-species author choices for particle attach points.

Convention across the corpus:
- Pokémon models use **bone index 0** for unused slots (root fallback).
- Human NPC models use **-1** (which is -1 i32, 0xFFFFFFFF) for unused slots.

The two groups load through different in-game code paths. -1 is safe on the NPC path but dangerous for Pokémon slots — empirically, a Pokémon-slot PKX with -1 in unused body_map positions does not load cleanly, consistent with the game dereferencing `body_map_bones[slot]` as an unchecked bone index.

### Root bone index
The root bone used for animation is typically at **bone index 1**, not 0. Bone 0 is usually a static wrapper / pm-number node that holds the model's top-level transform but isn't itself animated. Body-map slot 0 (the "root" key) commonly points at index 1 in game models.

### Animation slot ordering
PKX anim slots reference animations by **DAT index**, not by action name. `anim_entries[i].sub_anims[0].anim_index = j` means slot `i` plays the `j`-th animation in the exported `animated_joints[]` list. If the exporter writes actions in alphabetical order but slot 0 expects a specific battle-idle action, slot 0 ends up playing whatever sorts first, producing the "all battle states look like slow walking" symptom.

The exporter enumerates actions in PKX slot order so `DAT[i]` matches the action assigned to slot `i`, with alphabetical fallback for armatures that have no PKX metadata. Empty slots are seeded with the first bone-animating action so every `anim_index` resolves deterministically.

### XD vs Colosseum slot layout (and the inverted active flag)
The **per-slot animation ordering is identical between XD and Colosseum** for Pokémon. The three Pokémon shipped in both games (Absol, Torchic/`achamo`, Skarmory/`airmd`) have a byte-identical `anim_entries[i].sub_anims[0].anim_index` table across the two PKX formats — slot `i` references the same battle animation in both. So the importer reuses `XD_POKEMON_ANIM_NAMES` for Colosseum Pokémon (there is no distinct Colosseum-Pokémon ordering), and trainers use the per-game `XD_TRAINER_ANIM_NAMES` / `COLO_TRAINER_ANIM_NAMES` lists.

What *does* differ is the per-sub **`motion_type` polarity**, which is how a slot is marked real-vs-padding:
- **XD:** real slots carry `motion_type > 0` (1 = play-once, 2 = loop); unused padding slots are `motion_type = 0`.
- **Colosseum:** inverted — real slots carry `motion_type = 0`; unused padding slots carry `motion_type = 1` and point at `anim_index 0`.

Verified across all eight available Colosseum PKX files: real slots (0–10, plus slot 16 Take Flight on flyers) are uniformly `motion_type = 0`, and trailing padding slots are `motion_type = 1 → anim 0`. `shared/helpers/pkx_header.py::sub_anim_is_active` encodes this polarity so the describe-phase name map and the post-process metadata derivation agree on which slots reference a real DAT animation. An earlier heuristic that treated Colosseum "active" as `anim_type ∈ {loop, hit_reaction, compound} or motion_type > 0` was backwards: it dropped the real type-4 attack slots (1–7) and promoted the `motion_type = 1` padding slots.

The three sub-animation "trigger" refs (sleep-on / sleep-off / extra pose) are stored differently per format: XD keeps them as `PartAnimData` blocks, Colosseum as three plain ints in `colo_part_anim_refs`, but both share the same positional meaning. `active_part_anim_refs(header)` abstracts over the two layouts (returning `(trigger_index, anim_index)` for refs pointing at a real animation, index > 0) so the describe name map labels these `Sub SleepOnPose / Sub SleepOffPose / Sub Extra` in both games. For the Pokémon shipped in both, the Colosseum sub-trigger refs match the XD ones (e.g. Absol `6, 7, 5`), modulo per-build content differences (a model whose Colosseum build drops a sub-anim stores `-1` in that slot).

### PKX metadata round-trip tests

The metadata round trip is `PKXHeader → dat_pkx_* custom properties → PKXHeader`. Import derives the props (`post_process._derive_pkx_custom_props`, pure); export reconstructs the header from them (`exporter/phases/describe/helpers/scene.py::extract_pkx_header`). Two test layers exercise this:

- **Synthetic (pure, in `tests/test_pkx_metadata_round_trip.py`):** drives the *real* derive/extract functions through a duck-typed fake armature — `extract_pkx_header` only reads `.get()`, `.data.bones`, and the registered `dat_pkx_shiny_*` attrs, so no live Blender scene is needed. Covers XD and Colosseum fixtures (incl. shiny). Runs under plain `python3`.
- **Corpus diagnostic (`run_round_trips.py --pkx-metadata`, python3.11):** imports each real model, runs `post_process` to write the props, re-describes the scene, and diffs the reconstructed header against the original via `tools/pkx_metadata_compare.py`, reporting per-field divergences split XD / Colosseum.

Fidelity is judged by `compare_pkx_headers`, which classifies each field as a **violation** (must round-trip) or an **expected** divergence:

- *Exact:* species_id, particle_orientation, flags, distortion_*, head_bone (by name), anim_type, sub_anim_count, terminator, body_map (by name), timing.
- *Identity, not raw index:* sub-anim and part-anim animation references compare by **resolved action name**, because export re-orders the action list (e.g. Idle↔Special swap), so the raw `anim_index` legitimately changes while pointing at the same animation. Inactive padding refs are skipped.
- *Re-derived:* sub-anim `motion_type` per the polarity rule above (the round trip carries the action name, not the motion byte).
- *Expected divergences (documented, not failures):* `damage_flags` > 0x7FFFFFFF clamped to 0 (debug heap fill); an `anim_index` that lands outside the action table (uninitialised/garbage source ref) collapses to idx 0 / inactive; shiny brightness **alpha** forced to max on export; `type_id`, `colo_unknown_10/14` hard-coded by the exporter.

Result of the sweep (20 models: 12 XD + 8 Colosseum): **0 violations**, confirming the metadata survives import → export intact once the Colosseum `motion_type` polarity is honoured in `extract_pkx_header`.

**Shiny is never skipped, including identity.** `PKXContainer.shiny_params` and the exporter's `extract_shiny_params` return the shiny params even when they are identity/neutral (they only return `None` when the shiny region is out of bounds, or when `include_shiny` is off). So `post_process` stores the shiny route/brightness on the armature **and inserts the shiny filter into every model's textured materials** — an identity shiny is a visual no-op (and the mix factor is driven by the `dat_pkx_shiny` toggle, default off) but the values are explicit, so they round-trip and every model is shiny-ready. `_is_noop_shiny` remains as a predicate (used by tests / UI "has shiny data" checks) but no longer gates extraction.

The addon's registered shiny defaults are **identity routing + zero brightness**, so the only models that fall back to those defaults are ones with no shiny region at all (raw `.dat`) or imports with `include_shiny` off; they export as non-shiny rather than inheriting a stray preview tint. The non-identity "starting variant" is seeded only where a user deliberately adds shiny to an arbitrary model — `scripts/add_shiny_filter.py` (when the armature has no shiny yet) and the `prepare_*_for_pkx_export.py` prep scripts.

## Material + texture

### HASHED blend method from imports
GLB/FBX rips frequently set `blend_method='HASHED'` on materials even when the corresponding texture is fully opaque (or opaque with only anti-aliased edge pixels). HASHED in Blender is stochastic alpha-to-coverage, which EEVEE uses to approximate alpha-blended materials without proper sorting. This is a display-only concession and doesn't imply the material was authored as translucent.

Consequence for the exporter: the decision whether a material is "translucent" should not be driven by `blend_method` alone. (And currently, it's not driven by anything — see "Material translucency is unsupported" above.)

### UV slot indexing
The GX texture slot a material samples from (`Texture.source = 4 + uv_index`) is the **positional index** of the UV layer on the owning mesh — not anything parsed from the layer's name. Mesh export writes the `i`-th UV layer to `GX_VA_TEX0 + i`. Material export reads each `ShaderNodeUVMap`'s `uv_map` property and looks up its position in the owning mesh's `uv_layers` list. If no UVMap node is wired in, the slot defaults to 0.

The pre-`Float2` fix used a regex (`r'(\d+)$'`) to extract the slot from the layer name. That treated glTF-rip names like `Float2` as "this UV lives in slot 2", which the material side never agreed with — producing files where the mesh's vertex format published TEX2 but the texture's `source` field said TEX0, so the in-game sampler defaulted to (0,0). Positional indexing makes mesh and material agree by construction; the slot is the layer's position, full stop.

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
| BBB | importer.plan → build → exporter.describe → compare BR fields | Blender-leg fidelity (build + describe only) |
| IBI | importer.plan → exporter.plan → compare IR fields | Plan ⇄ Plan fidelity through BR — no bpy build/describe leg |

NIN, BBB, and IBI scores are computed against the full original data — not just the fields the exporter has implemented — so percentages naturally rise as more export features come online. IBI is now a pure Plan round-trip (IR → BR via the importer's Plan, BR → IR via the exporter's Plan); it isolates IR↔BR conversion fidelity and no longer needs a bpy runtime, so removing the build/describe leg drops the noise that leg added (fcurve resampling, normal recomputation) and tends to raise per-category scores — animations in particular jump because the lossy fcurve sample/sparsify round-trip is gone. BBB still needs a real bpy runtime; the unit-test stubs in `tests/test_plan_round_trips.py` stay skipped, and live coverage is in `tests/round_trip/run_round_trips.py` (run with `python3.11`).

### Blender Python version
Use `python3.11` for round-trip tests. The default `python3` on the dev machine is 3.10, which ships an older `bpy==3.4.0` that lacks APIs like `action.slots` that the current codebase requires. `python3.11` pairs with `bpy==4.5.7`.

## Exporter policies

### Matrix baking
The prep script bakes every armature's and child mesh's `matrix_world` into the geometry data before export. The exporter then rejects any armature or child mesh that still has a non-identity `matrix_world`, so the bone (decompose) and vertex (matmul) transform paths stay in the same reference frame.

A consequence worth knowing: `Armature.transform(world)` in Blender 4.5 applies rotation and scale correctly but silently drops the translation column on armatures. Rigs positioned off-origin in object mode need `bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)` (or manual repositioning to world origin) before the prep script runs, otherwise the mesh and skeleton end up in different frames.

The bake also scales translation fcurves to match the new rest frame. Pose-bone `location` keyframes and object-level `location` keyframes are both multiplied by the armature's pre-bake world scale; rotations and pose-bone scales are dimensionless and untouched. Actions are scoped per armature — each armature scales the actions it owns (active + NLA on itself or its child meshes, plus any floating action whose pose-bone fcurves name a bone on that rig), with a `seen` set guarding against double-scaling if an action somehow appears under multiple rigs.

### Root joint orientation (must be identity; manual fix)
The exported **root JOBJ rotation must be identity** — every game-native model has one. The game (`ModelSequence::LoadData` → render path) applies the root joint's own rotation as the model's base orientation and does **not** cancel it the way a full skinning solve does, so a non-identity root joint turns the whole model in-game (typically 90°) even though Blender — which evaluates the rest pose as the identity deformation — renders it correctly. A clean export→import round-trip also hides it, because the importer reconstructs from the same joint tree.

A from-scratch rig hits this when its root bone isn't axis-aligned. The exporter converts each bone's Blender rest matrix through the Z-up→Y-up coord rotation; the root joint comes out identity exactly when the root bone's world rest equals the *forward* coord rotation (+90° about X — a bone pointing straight up with **roll 0**). A hand-built root with any other roll/orientation exports a rotated root joint. Imported rigs are already canonical (they store Y-up bones with a +90°-X `matrix_basis`), so this only bites scratch/GLB rigs.

**Current state.** `pre_process._validate_root_bone_orientation` (+ pure `_check_root_bone_orientation`) **rejects** any scene whose root would export a non-identity root JOBJ, with an actionable message. The prep scripts do **not** auto-fix it — an earlier in-place auto-normalize was reverted (see below). Resolution is the author's job.

**Manual workaround.** Make the root bone axis-aligned before export: in Edit mode select the root bone and set **Roll = 0** with it pointing up (+Z), or `Armature → Bone Roll → Clear Roll` then re-aim. Do this **before** animating the root — changing the root's rest after it's animated requires re-binding its animation (the same problem the auto-fix hit). If the root is already animated, the cleanest manual route is the "insert canonical parent" move described below, done by hand: add an axis-aligned `Origin` bone at the rig origin and parent the existing root to it.

**Mesh and root bone in different orientations.** A separate variant (seen on a hand-assembled rig: a **Z-up mesh under a Y-up root bone**) needs more than re-aiming the bone, because the mesh is skinned to it — rotating the root to axis-aligned rotates the mesh with it, leaving the mesh wrong. The fix is two rotations that cancel on the bone but not the mesh: **rotate the root bone to axis-aligned** (the mesh follows), then **rotate the mesh object by the inverse of that same rotation**. The bone exports identity; the mesh returns to its correct orientation. This stays manual for the same reason the others do — the prep scripts can't safely automate it (a blanket re-orient of the whole rig would leave the mesh mis-oriented).

**Why the obvious auto-fix failed.** Reorienting the existing root bone's rest in place and re-binding its own animation *looks* correct (the root bone's world pose is preserved) but **breaks every direct child when the root is animated**. Blender evaluates a child as `child_world = root_pose @ (root_rest⁻¹ @ child_rest) @ child_basis`. Changing `root_rest` changes the `root_rest⁻¹ @ child_rest` term; the child's own animation doesn't compensate, so whenever the root is posed (≠ rest), the children — and the geometry skinned to them — rotate by the rest delta. Verified: after the in-place fix, the root bone's world motion was preserved (0.0) but `BODY`/`FACE` rotated 1.0 (90°) at every animated frame. Compensating the direct children too (constant `K = child_rest⁻¹ @ D @ child_rest`, `D = new_root_rest @ old_root_rest⁻¹`, including its translation, plus injecting keyframes onto children unanimated in root-animated actions) is correct in principle but fiddly, error-prone, and bloats actions with synthetic keyframes.

**Recommended robust solution: insert a canonical root *parent*.** Instead of reorienting the existing root, add a new axis-aligned bone (`Origin`, up + roll 0) at the rig origin and re-parent the existing root to it. The existing root keeps its orientation — now a *child* rotation that cancels through normal skinning (its descendants are deformers with IBMs) — so **nothing animated or geometric changes**. The new bone is the model root and exports identity. Verified on the field model: posed-mesh displacement **0.00000** at every frame across all actions, and the exported root JOBJ rotation is `(0,0,0)`. This is the recommended **manual** route; it is deliberately **not** automated in the prep scripts — the in-place auto-normalize above was tried and reverted, and a blanket re-orient can't handle the mesh-vs-bone-mismatch variant either.

If this is ever revisited as an auto-fix (not currently planned):
- Run before `apply_pkx_metadata` (so the body-map `origin` slot resolves to the new root) and before `reparent_meshes_to_holder_bones`. No-op when the current root already exports identity (idempotent: a second run sees the canonical `Origin` at index 0 and skips).
- The +1 bone shifts indices, but the PKX body-map / head-bone are resolved by **name** in describe, so nothing breaks; just ensure the new root's name is unique (suffix on collision) and decide whether `origin` should point at the new root vs the old one (both sit at the rig origin, so the attach position is identical either way).
- New root is a non-deformer (no weights/IBM), matching the game's root-joint convention.
- Re-validate with the `pre_process` guard, which already accepts a canonical root. Add a posed-mesh-preservation regression check (sample a few frames per action before/after; assert ~0 displacement) so a future change can't silently reintroduce the in-place breakage.

### Data section layout (exported DAT)
The serializer writes raw buffers into the data section in the same order Sysdolphin's compiler used: **vertex buffers → display lists → parsed structs (bulk) → palettes → image pixels**. Image pixel buffers and vertex buffers are content-deduplicated, so multiple Texture / Vertex references that share a buffer contribute one block to the file. `dat_builder.build` realises this as four phases — `writePrimitivePointers` (vertex), `writePrivateData` + struct allocation (display lists + structs), `writePaletteData`, `writeImageData`. Pixel buffers therefore land near the end of the data section and never at relative offset 0, where they would alias the "null pointer" sentinel.

### Struct ordering convention (reverse-engineered; BNB analysis)
Sysdolphin's compiler does **not** emit the "parsed structs (bulk)" in a single tree walk — it groups them by type into a fixed phase sequence, post-order DFS within each phase. Reverse-engineered from game-native PKX files (absol, metamon, pikachu, deoxys all agree by struct address order):

1. **Materials** — per `MaterialObject`, in tree order, post-order: `Image → Texture → Material (+ inline RGBAColor block) → [PixelEngine] → MaterialObject`, deduped when shared.
2. **Envelopes** — `EnvelopeList` / `Envelope`.
3. **Vertex descriptors** — `Vertex` / `VertexList`.
4. **Geometry** — `PObject → Mesh` (DObject), post-order.
5. **Skeleton** — `Joint` (DFS).
6. **Bone animation** — `Frame`, `Animation`, `AnimationJoint`.
7. **Material animation** — `TextureAnimation`, `MaterialAnimation`, `MaterialAnimationJoint`.
8. **Scene** — `WObject`, `Light`, `Camera`, then `ModelSet` / `CameraSet` / `LightSet`, then `SceneData` / `BoundBox` (roots last).

`DATBuilder`'s base traversal is a single DFS post-order; the animation phases (6–7) are now regrouped to match the original (see below). The upstream phases (1–5) still emit in DFS order — the remaining BNB gap.

#### Animation region layout (cracked)
Within the bone- and material-animation phases, Sysdolphin writes each **sequence** (one AnimationJoint / MaterialAnimationJoint tree, mirroring the skeleton) bottom-up by layer, *not* depth-first per joint:

- **Bone:** per sequence — all frame/animation data first (each animated joint's keyframe buffers then frame structs then its Animation), then all the AnimationJoint structs (pre-order, root first). Game-native files batch the joints in exactly *N sequences × skeleton-size* groups (absol: 8 × 104).
- **Material:** per sequence — all frame/animation data, then `TextureAnimation` structs, then `MaterialAnimation` structs, then `MaterialAnimationJoint` structs.
- **Frame keyframe buffers** are pooled (all an animation's buffers, each 4-byte aligned, then all its Frame structs) — *not* interleaved buffer-then-struct.

Each subtree-owning node declares its own serialization order: `AnimationJoint` and `MaterialAnimationJoint` set `serializes_subtree = True` and implement `serializationOrder()` (returning the flat ordered node list for their tree). `DATBuilder._serialization_blocks` is a generic mechanism — it finds the subtree roots (a `serializes_subtree` node not referenced as another's `child`/`next`), calls each root's `serializationOrder()`, and `_write_block` emits the result, pooling consecutive Frame runs. Measured with `tools/bnb_region_metric.py` (which isolates the animation region and normalises offsets to its start — global BNB is useless for convergence because an upstream size drift shifts every downstream pointer value at once): the animation region went from **0 → 99.6%** of items at the exact relative offset (the residual 0.4% is a subtle material-anim data sub-order at the bone/material boundary). NBN stays 92.3% and all unit tests pass.

#### Why global BNB still lags on absol (upstream gate)
BNB is a whole-file fuzzy match of 4-byte word *values* (dominated by pointer values). Even with the animation region internally byte-correct, its **absolute** start is shifted by the upstream materials/geometry/skeleton region, which is still **+1 648 bytes** (pure padding/ordering — per-type struct byte totals are identical; the region just isn't grouped into phases 1–5 yet) and starts with `Joint` instead of `Image`. That shift changes every animation pointer's value, so global BNB barely moves on absol (86.4→86.7%). Models with a small upstream region already benefit strongly — **metamon BNB 99.1% / NBN 100%**, pikachu 90.6%. **NBN/NIN remain the metrics that track real export accuracy.**

**Upstream — partially cracked (materials), walled on envelopes.** The non-animation phase order is **materials → envelopes → vertex descriptors → geometry → skeleton → animations → scene**. Convergence was driven by a *multi-model sweep* (try many systematic candidate orderings, score each against ground truth across absol/metamon/pikachu/deoxys/eievui, keep the one that wins on all five) rather than guessing — see the `feedback_systematic_variant_convergence` memory.

- **Materials — cracked (5/5 models), integrated.** MaterialObjects are emitted in the **reverse of (joint post-order → each joint's mesh-list MaterialObjects, first-encounter dedup)** (`DATBuilder._material_object_order`). `joint.property` holds the head DObject (stored as an address; resolve via a `mesh.address → Mesh` map). Per MObject the block is **`PixelEngine → Image → Texture → Material(+inline RGBA) → MaterialObject`** — the PixelEngine leads (declared by `MaterialObject.serialization_field_order`, applied during the builder's DFS).
- **Vertex descriptors — cracked (5/5 models), integrated.** `VertexList`s use the *same* reverse joint-post order, reached via each mesh's PObject chain (`_vertex_list_order`). Geometry (`PObject`/`Mesh`) and skeleton (`Joint`) are already correctly ordered by the DFS, so they only need grouping at their phase position.
- **Envelopes — deduplicated; internal order still walled.** Two separate problems. (1) **Dedup** (solved): the original content-deduplicates `EnvelopeList`s — see the dedup bullet above. This was the real blocker; the earlier "no traversal beats 16/462" sweeps were ordering 193 non-deduped objects against a 98-struct original, which is impossible. With dedup the region is the correct *size*, so all downstream phases land at the right offsets. (2) **Internal order** (still open): the order of the 98 unique structs is a *global* interleaving across PObjects — consecutive original addresses come from different PObjects, and even best-case per-PObject sorting under reverse-joint-post leaves ~43/98 misplaced. It doesn't follow any joint/mesh/PObject traversal tried, pointing to the compiler's matrix-table allocation order during display-list vertex processing (which we don't reconstruct). The internal mis-order costs only a handful of struct bytes locally (the region size is right), so it no longer cascades downstream.

**Architecture & integration.** The overarching phase order lives in the builder (`DATBuilder._ordered_node_list`: materials → envelopes → vertices → geometry → skeleton → animations + scene), while each node owns its *local* ordering — `serializes_subtree` + `serializationOrder()` for whole-subtree regroupings (the animation joint trees and `SceneData`) and `serialization_field_order` for direct-children order (MaterialObject's PixelEngine-first). The builder reuses the local orders already baked into node_list; it only regroups blocks.

- **Texture animations — cracked (5/5 models), in `MaterialAnimationJoint.serializationOrder`.** Within each joint, texture animations are emitted in **reverse material-animation order** (a later MA's texture animation precedes an earlier one's) while each MA's own `texture_animation` linked-list stays **forward**; the data blocks lead, then the structs. This single rule reconciles two model shapes that looked contradictory: one joint with two TA-bearing MAs (reverse-MA, e.g. absol) and one MA with a multi-element `ta.next` chain (forward-within-chain, e.g. deoxys).
- **Scene tail — cracked (5/5 models), in `SceneData.serializationOrder`.** The scene emits in two bands: **leaves** first (each light's `position` WObject + `Light` struct, then the camera's `position`/`interest` WObjects + `Camera` struct), then **containers** (`ModelSet`s forward, `CameraSet`, `LightSet`s), with both the light-leaf band and the LightSet band in **reverse LightSet-index order**; `SceneData` itself is last. This also clears the inline `RGBAColor` residual (light colours move with their lights).
- **Multi-texture chain — cracked (deoxys), via `MaterialObject.serialization_reverse_chain_fields`.** A material's `texture.next` linked-list is emitted **deepest-first, head last** — the whole chain reversed, each texture keeping its own image/tev(+inline colours)/struct sub-order. Single-texture materials (a chain of one) are unaffected, which is why only multi-texture models exercise it. Implemented generically: a node may list `next`-chain fields in `serialization_reverse_chain_fields` and `DATBuilder._dfsPostOrder` walks them in reverse (each element with its own `next` suppressed).
- **Palettes & scene tail — trailing phases.** The compiler emits all `Palette` structs together near the very end of the file, immediately before the scene tail, as `[animations][palettes][scene tail][BoundBox]` — *not* inline with their texture (the texture only holds a pointer). `_ordered_node_list` buckets palettes and the scene-tail types (`_SCENE_TYPES`) out of `rest` and appends them last (`… + rest + palettes + scene`). An earlier attempt grouped palettes into the material block via `_MATERIAL_TYPES`; that fixed the per-type LIS but inserted ~16 bytes per paletted texture into the material region, shifting every downstream struct — visible as a uniform pointer drift through the whole animation region on indexed-texture models (eievui, pikachu).
- **Envelope lists — content-deduplicated.** The compiler emits one `EnvelopeList` struct per unique `(joint, weight)` sequence and shares it across PObject slots; our parse makes a separate object per slot (`EnvelopeList` is `is_cachable=False`). `DATBuilder` collapses them at write time (`_envelope_content_key`): the first object of each content key is written, later duplicates alias its address and are skipped in Phase 3 (so they neither re-emit bytes nor double-add relocations). This restores the correct envelope-region *size* (e.g. absol 193 objects → 98 structs), which aligns every downstream phase — without it the region ran ~1.5–2 KB long and shifted the back half of the file. The *internal* order of the deduped set is still uncracked (see below).

**Metric — ordering correctness, then BNB.** Per-phase convergence is judged by `tools/bnb_node_ordinals.py --lis` (N − LIS, robust to absolute region shifts); whole-file fidelity by `compute_bnb_score` (fuzzy 4-byte-word match). With materials, vertices, texture-animations, multi-texture chains, palettes, the scene tail, **and envelope dedup** integrated, every model is now near byte-exact:

| model | BNB | dominant residual |
|---|---|---|
| absol | 99.74% | scene cross-ref pointers |
| metamon | 99.87% | scene + vertex-list pointers |
| pikachu | 99.86% | scene + texture/palette pointers |
| deoxys | 99.56% | envelope internal order → material/geometry pointer cascade |
| eievui | 99.92% | scene + light pointers |

**File-tail layout (cracked).** Sysdolphin lays the tail out as `[image pixel data][palette LUT+struct, interleaved per palette][scene tail][BoundBox]` — every data buffer precedes the scene, and palette *structs* are interleaved with their LUT data, not grouped with the material structs. `DATBuilder.build` defers palette and scene-tail struct allocation out of the main struct pass and emits them after the image-data pass (Phase 2.6 = palettes, 2.7 = scene). Image pixel blocks are written in **struct-address order** (not node_list/DFS order) so their `data_address` pointers ascend with the structs. This fixed the two cascades that were displacing the whole back half of the file on indexed-texture models. The **vertex-descriptor NULL terminator** is emitted with the compiler's fixed non-zero descriptor `(attribute=0xFF, attribute_type=2, component_type=4)` — a constant across every game-native VertexList — rather than all-zeros.

The remaining <0.5% is: (1) the **envelope internal order** (uncracked — worst on deoxys, which has many envelopes but no palettes), and (2) a handful of **scene cross-reference pointers**. The large pre-dedup gaps (absol 86.9%, eievui/metamon ~82%) came from three cascades now fixed: the envelope-region over-size, the inline-palette per-texture drift, and the scene/data-buffer tail ordering.

### DAT file length must equal `header.file_size` (no trailing pad on a raw .dat)
`HSD_ArchiveParse` (verified in both the XD and Chibi-Robo disassemblies — same shared HSD library) asserts `header.file_size == expectedSize`, where `expectedSize` is the byte length the resource system recorded for the file. For a **raw `.dat`** loaded straight from an FST/fsys, that recorded length is the on-disk entry size, so any trailing padding beyond `header.file_size` makes the assertion fail and the model never loads. `dat_builder` already ends the file right after the last symbol string (length == `file_size`); the serialize phase must **not** add 0x20 padding. The 0x20 alignment a container needs is applied in the **package phase, for `.pkx` output only** (`package._pad_dat_to_0x20`): inside a PKX the embedded DAT may be padded because the inner DAT's size is read from the DAT/PKX header (`pkx.py` delimits it by `header.file_size`), so the pad sits in the trailer and is invisible to the size check. That header-vs-fsys distinction is why XD Pokémon models (always PKX-wrapped) never hit this, while a bare `.dat` does.

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

### Default export lighting
When a scene has no lights, `scripts/prepare_for_pkx_export.py::prepare_lights` synthesises the standard Colo/XD 4-light rig (1 ambient POINT + 3 directional SUN). The three SUN directions are the corpus-typical light vectors, derived by averaging the per-slot normalised GX direction across the 69 game-native PKX models that ship exactly three directional lights, then re-normalising:

| Slot | Colour (u8) | GX (Y-up) unit direction | Rough sense |
|---|---|---|---|
| Main | 204 | `( 0.530,  0.660,  0.533)` | above-front |
| Fill | 102 | `(-0.352,  0.520, -0.778)` | above-behind |
| Back |  76 | `(-0.712, -0.540,  0.450)` | below-front |

The earlier prep rig used hand-picked `rotation_euler` angles that all pointed *downward* (negative GX-Y) — visibly wrong against real models, whose dominant Main/Fill lights come from *above* (positive GX-Y). The prep script now builds each SUN with the **same rig the importer produces** (`build_blender/helpers/lights.py`): a `PLAIN_AXES` target empty named `<light>_target` at the GX direction (expressed Z-up as `(gx, -gz, gy)`), plus a `TRACK_TO` constraint (`TRACK_NEGATIVE_Z` / `UP_Y`) aiming the lamp at it. The exporter recovers the direction from that target (`describe/helpers/lights.py::_read_track_to_target` → `plan_lights`) — the same path it uses for imported lights, rather than the lamp's bare −Z axis. The GX→Blender map `(gx, gy, gz) → (gx, -gz, gy)` is the exact inverse of `plan_lights`'s collapse `(bx, by, bz) → (bx, bz, -by)`, so a prep-created light round-trips back to its listed GX direction (verified to ~1e-5).

### Shader graph socket keys
`BRLink.from_output` / `BRLink.to_input` and `BRNode.input_defaults` keys reference shader-node sockets by their Blender **socket identifier** — a single string convention, no exceptions. The identifier is unique within a node even when display *names* collide (a Math node's three inputs are `'Value'` / `'Value_001'` / `'Value_002'`; a VectorMath's are `'Vector'` / `'Vector_001'` / `'Vector_002'`).

Why the identifier and not the display name or the positional index: `socket.name` is not unique (the duplicate cases above), and the positional index shifts between Blender versions (Principled's input order changes as sockets are added/reordered). The identifier is both unique *and* version-stable — Blender treats it as the canonical socket reference — so it's the only collision-free, robust key.

Producers and consumers:
- Exporter describe reads each live socket's `.identifier` directly (`exporter/phases/describe/helpers/materials.py`).
- Importer plan's `BRGraphBuilder` lets callers wire sockets by convenient integer index and rewrites each to its identifier at storage time via the `_SOCKET_IDS` table (`node_type → (input identifiers, output identifiers)`, positional, Blender 4.5). A tracked node whose type is missing from the table, or an out-of-range index, raises at plan time — so a gap surfaces immediately rather than as an unresolvable link at build time.
- `build_blender` resolves an identifier by scanning `node.inputs` / `node.outputs` for `socket.identifier == key`. (`node.inputs[key]` matches `.name`, not the identifier, so the scan is required — that's the one ergonomic cost of identifiers.)
- The exporter plan decoder reads identifiers directly; the two duplicate-socket cases it inspects already used the right identifier (a Math node's first input `'Value'`, a VectorMath's second input `'Vector_001'`).

`_SOCKET_IDS` is the only Blender-version-sensitive data in this path; if a future Blender renames a socket, update it there.

## Particles (GPT1)

15 battle models in Colosseum / XD ship with embedded GPT1 particle data — the flame-, gas- and mist-themed Pokémon (Moltres, Articuno, Charmander/Charmeleon/Charizard, Gastly, Magmar, Magcargo, Torkoal, Koffing, Weezing, Vaporeon, plus the three shiny variants `rare_fire`, `rare_freezer`, `rare_lizardon`).

The GPT1 parser, disassembler, IR types, and compose-side assembler are all in place and unit-tested, but no Blender objects are created from the data and the exporter does not write the GPT1 region. The blocker is the **generator → bone binding**: we have not been able to locate the table or code path that pairs each generator in a model's GPT1 with the body-map slot it renders from. Investigation has ruled out:

- The HSD `JOBJ_PTCL` flag (unset on all 15 models).
- `_particleJObjCallback`.
- The PKX header body map (a bone lookup table, not a binding).
- WZX move files (carry move/attack effects only).
- The `common.rel` index table.
- The DOL data section around `PKXPokemonModels`.

Visualising generators at the armature origin without a correct bone attachment is misleading in practice (every flame floats in the wrong place), so the import stub logs generator/texture counts on the armature but creates nothing in the scene. Re-exported `.pkx` files drop the GPT1 region — the original file should be retained if effects need to be preserved.

## Convention: code comments vs. documentation

Code comments in `exporter/`, `importer/`, `shared/`, `scripts/`, `tools/` describe what the code does and why it's structured the way it is. They do **not**:

- Name specific model files (Pokémon species, asset filenames, etc.)
- Quote empirical measurements from in-game tests.
- Describe the debugging narrative that led to a fix.

Any such information belongs in `technical-docs/` (usually this file or `exporter_setup.md`). The rationale is that code comments age out faster than the code they annotate — a specific model that motivated a fix is rarely the right mental model for the next person encountering the code, and an empirical measurement gets stale the moment the code changes shape.
