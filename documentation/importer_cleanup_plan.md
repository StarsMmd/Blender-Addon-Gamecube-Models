# Importer Cleanup Plan — Parallel Session

Short-lived working document for a targeted cleanup of three importer-phase helpers. Delete this file once all three items land and any new findings are folded into [implementation_notes.md](implementation_notes.md).

## Goal

Improve testability and readability of three specific files in the importer by extracting logic into pure, unit-testable helpers with clear I/O. Be pragmatic — if a chunk is already clean, leave it alone.

## Coordination with the parallel Plan-phase migration

A separate session is migrating the importer from `IR → build_blender` to `IR → Plan → BR → build_blender`. That migration will rewrite parts of `build_blender/helpers/` but leaves `describe/helpers/` and `post_process/` untouched. **This cleanup plan is scoped to files the migration doesn't touch**, so merges will be clean.

**Files off-limits** (the Plan-phase session is actively working on them — don't touch):
- `importer/phases/build_blender/*`
- `importer/phases/plan/*`
- `shared/BR/*`
- `tests/test_plan_*`

**Files in scope for this cleanup:**
- `importer/phases/describe/helpers/meshes.py`
- `importer/phases/describe/helpers/animations.py`
- `importer/phases/post_process/post_process.py`

If you need to modify something outside those, stop and check in.

## Item 1 — Flatten `describe/helpers/meshes.py` closures

**File:** `importer/phases/describe/helpers/meshes.py` (571 lines).

**Current state:** `describe_meshes` (starting line 38) opens three nested `def`s that capture `bones`, `joint_to_bone_index`, `options`, `image_cache`, `logger` via closure:

- `_walk_joints` (line 60)
- `_walk_mesh_chain` (line 72)
- `_describe_pobj` (line 102)

Closures mean none of them can be called independently for testing.

**Target:** promote all three to module-level functions taking their captures as explicit args. No behavioural change. Update `describe_meshes` to call them with explicit arguments.

Signature shapes (check against actual usage):

```python
def _walk_joints(joint, bones, joint_to_bone_index, options, image_cache, logger, meshes):
def _walk_mesh_chain(mesh_node, joint, bone_index, bones, joint_to_bone_index, options, image_cache, logger, meshes):
def _describe_pobj(pobj, joint, bone_index, count, bones, joint_to_bone_index, options, image_cache, logger, ir_material=None):
```

Keep them private (underscore prefix) — they're still implementation detail, just module-level.

**Tests:** extend `tests/test_describe_meshes.py`. At minimum, add one test per extracted helper that calls it directly with synthetic inputs (an empty `bones` list, a hand-built fake Joint/POBJ, etc.). You don't need to replicate the full binary-fixture setup used by the existing suite — assertions on behaviour of individual helpers are enough.

**Acceptance:** full `pytest tests/` stays green; at least one direct-call test per extracted helper.

## Item 2 — Split `describe/helpers/animations.py::_describe_bone_track`

**File:** `importer/phases/describe/helpers/animations.py` (406 lines).

**Current state:** `_describe_bone_track` (starting line 264) walks the `aobj.frame` linked list, decodes keyframes per channel, scales location keyframes to meters, builds the `rest_local_matrix`, and assembles the `IRBoneTrack` — all in one ~75-line function.

**Target:** extract the Fobj linked-list walk + channel decode into a pure helper:

```python
def _decode_bone_channels(aobj, logger=None, options=None):
    """Walk the Fobj chain and decode keyframes per channel.

    Returns:
        rotation: list[list[IRKeyframe]] of length 3 (X/Y/Z).
        location: list[list[IRKeyframe]] of length 3 (in meters, scaled from GC units).
        scale: list[list[IRKeyframe]] of length 3.
        spline_path: IRSplinePath or None.
    """
```

`_describe_bone_track` then calls `_decode_bone_channels`, composes `rest_local_matrix`, and returns the `IRBoneTrack`. Two smaller functions, each with a clear signature.

**Tests:** new file `tests/test_describe_bone_channel_decode.py`. Build a fake Fobj chain (you can construct parsed Fobj instances in-memory — see how existing tests like `tests/test_describe_bone_anim_frame_range.py` do it, or use `helpers.py::build_frame` and parse into a real Fobj). Assert per-channel keyframe counts and values.

**Acceptance:** full suite green; dedicated tests for the new decode helper.

## Item 3 — Factor `post_process/post_process.py::_store_pkx_metadata`

**File:** `importer/phases/post_process/post_process.py` (422 lines).

**Current state:** `_store_pkx_metadata` (starting line 214) is ~130 lines mixing PKX struct reading, semantic-name derivation (XD vs Colosseum detection, anim slot naming, sub-animation references), and Blender armature custom-property writes.

**Note:** post-process *is* allowed to have bpy calls (it's outside the importer's purity contract) but the semantic derivation logic has no reason to touch bpy.

**Target:** extract a pure `_derive_pkx_custom_props(pkx_header, actions)` function that returns a `dict[str, value]` of all properties we'd write to the armature. `_store_pkx_metadata` becomes:

```python
def _store_pkx_metadata(armature, pkx_header, logger, actions=None):
    props = _derive_pkx_custom_props(pkx_header, actions)
    for key, value in props.items():
        armature[key] = value
    # Any remaining bpy-specific logic (custom-property UI, etc.)
```

The derivation is where the interesting edge cases live (XD/Colo detection by `is_xd` + `species_id`, anim slot semantic naming, sub-animation references). That's the unit-testable part.

**Tests:** new file `tests/test_pkx_custom_props.py`. Build synthetic `PKXHeader` and `Action` fixtures and assert the derived prop dict. Cover XD-vs-Colo detection and anim slot naming.

**Acceptance:** full suite green; `_derive_pkx_custom_props` has direct unit tests for at least XD pokemon, XD trainer, Colosseum, and the no-pkx-header case.

## Deferred — don't attempt in this session

- **`build_blender/helpers/animations.py::_bake_bone_track` split** — the Plan phase migration's Stage 3 will subsume it.
- **`build_blender/helpers/meshes.py` compute/apply split** — Plan Stage 2 will subsume it.
- **`build_blender/helpers/materials.py`** — Plan Stage 4, and genuinely hard to purify without a node-graph IR.

## Project conventions you must follow

- **Defensive imports.** Every `from shared.…` / `from importer.…` / `from exporter.…` import inside the addon package must be wrapped in `try: relative / except: absolute`. See any existing file for the pattern. Forgetting this breaks Blender addon loading silently.
- **No bpy in `shared/` or `describe/`.** Describe is platform-agnostic by contract. Post-process may use bpy.
- **No game files in the repository ever.** Tests build fixtures in-memory.
- **Logger parameter.** Functions default to `StubLogger()`, never `None`. Use `logger.info()` / `logger.debug()`, not `print()`.
- **Bug-fix regression tests.** Whenever you fix a bug while cleaning up, add a test for it.
- **Comment discipline.** Don't reference specific models/species in code comments or describe the debugging narrative. Comments explain *why* non-obvious code does what it does. Narrative belongs in [implementation_notes.md](implementation_notes.md).
- **Run the full suite.** `cd` into the project root and `python3 -m pytest tests/` should be green at every commit. Count at the start of your session: **944 passed, 11 skipped**.
- **Commit granularity.** One commit per item. Commit message format: see `git log` for recent examples.

## Getting started

1. `git status` to confirm a clean working tree (or stash any work-in-progress).
2. Pick one of Items 1-3 (any order — no dependencies between them).
3. Read the target file + the relevant existing tests to understand the fixture style.
4. Make the change.
5. Run `python3 -m pytest tests/ -q` — must be green.
6. Commit.
7. Pick the next item.

Each item is self-contained and should take under an hour.
