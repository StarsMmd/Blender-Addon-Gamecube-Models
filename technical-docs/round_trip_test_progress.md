# Round-Trip Test Progress

Each round-trip test works by taking the result of an import step, running the equivalent export step on it, and checking how close the output is to what we started with. This is the most direct way to verify that each exporter step works as intended.

This document tracks the fidelity of the export pipeline by measuring how accurately data survives each round-trip path. When NBN, NIN, IBI, and BBB all approach 100%, the exporter is functionally complete.

---

## Round-Trip Types

The full pipeline shape is:

```
binary → parse → IR → importer.plan → BR → build → Blender
                                                      │
                                                      ▼
binary ← serialise ← IR ← exporter.plan ← BR ← describe
```

Each round-trip type bounds a different segment.

### Node tree → Binary → Node tree (NBN)

Parse a DAT binary into a node tree, serialize it back via DATBuilder, reparse the output, and compare node fields. Measures whether the DATBuilder preserves all node data through the binary format. Mismatches typically come from pointer resolution edge cases or alignment differences.

### Node tree → IR → Node tree (NIN)

Parse a DAT binary into a node tree, run the importer's describe phase to produce an IRScene, then run the exporter's compose phase to reconstruct a node tree. Compare the composed node tree against the original. Measures how much data survives the IR round-trip. The NIN score reflects the **full** node tree (not just the fields we've implemented compose for), so it naturally increases as more compose helpers are added.

### BR → Blender → BR (BBB)

Plan an IRScene into a BRScene via the importer's plan phase, build it into Blender via the importer's build phase, then read it back via the exporter's describe phase. Compare the two BRScenes using per-category scoring. Bounds **only** the Blender-facing leg of the pipeline (build + describe) — no IR↔BR conversion crosses the comparison, so any drift here is either a fidelity bug in build/describe or an inherent limitation of representing the BR data inside Blender.

### IR → BR → IR (IBI)

Plan IR → BR via the importer's plan, then run the exporter's plan to recover a new IRScene directly from that BR — **no bpy build/describe leg**. Compare the two IR scenes using category-weighted scoring — each IR category (bones, meshes, materials, animations, constraints, lights) is scored independently, then averaged across categories that have data. This prevents large vertex arrays from inflating the score. IBI isolates the two Plan phases (importer IR→BR and exporter BR→IR) back to back, so any drift is a pure IR↔BR conversion bug, not noise from the Blender round-trip (fcurve resampling, normal recomputation). It requires `mathutils` but not a bpy build context. (This relies on the exporter Plan being self-sufficient — it derives IR bones/meshes from BR via `plan_armature`/`plan_meshes`/`merge_meshes` rather than reading a stash that only the bpy describe phase could populate.)

### Binary → Node tree → Binary (BNB)

Parse a DAT binary, write it back, and compare the output bytes against the input using a fuzzy 4-byte word matching algorithm. This measures binary-level fidelity — whether the output file would be byte-identical to the input. Exact 1:1 binary matches are a stretch goal that will require matching the original HAL DAT compiler's layout conventions (alignment, node ordering, padding). A high BNB score is purely aesthetic — it has no functional benefit. NBN determines the practical accuracy of the exporter.

### What round-trips deliberately ignore

The comparators skip these field categories so the score reflects model data, not pipeline plumbing:

- **Pre-computed matrices** derived from SRT — `world_matrix`, `local_matrix`, `normalized_world_matrix`, `normalized_local_matrix`, `scale_correction`, `accumulated_scale`. They're cached convenience fields, not independent data.
- **Pre-computed deformed geometry** — `deformed_vertices`, `deformed_normals`. Derived from bone weights + vertices.
- **DAT file offsets** used as cache keys — `image_id`, `palette_id`. Per-file binary identifiers, not model content.
- **Internal opaque ids** — `id` (IRMesh / BRMesh foreign-key target), `cache_key`, `dedup_key`, `material_mesh_name`. These are pipeline-internal cross-references; the importer and exporter mint them independently for their own binding purposes, and identity across a build → describe round-trip isn't a fidelity concern.

---

## Test Results

**Overall export pipeline completion (77 character/Pokémon models): ✅ 87.8%** _(weighted: NBN 20% × 98.6 + NIN 35% × 77.0 + BBB 15% × 83.4 + IBI 25% × 95.2 + BNB 5% × 96.3)_

_Average health: 🔴 0-20% · 🟠 21-40% · 🟡 41-60% · 🔵 61-80% · ✅ 81-100%_

Scores below come from the full corpus in `~/Documents/Projects/DAT plugin/models/`, run with `python3.11` and `bpy==4.5.7`. All scores displayed as `match%(error/miss)` — see "How Scores Are Computed" for definitions.

> **Note on map results.** The runner now skips **BBB** on `.rdat` map archives by default (`--maps-bbb` to force it) — the bpy build is minutes-slow there and was the cause of the old `D1_out` hang, which now completes and is included below. The map BBB column carries the values from the last full BBB sweep (build/describe is unchanged since), `D1_out` excepted (never measured). Re-generate the other columns via `python3 tools/parse_rt_results.py <runner-output>`.

<!-- AUTO-GENERATED-RESULTS START -->

### Character / Pokémon Models

| Model | Game | NBN ✅ | NIN 🔵 | BBB ✅ | IBI ✅ | BNB ✅ |
|---|---|---|---|---|---|---|
| absol | Colo | 100.0%(0/0) | 79.3%(21/0) | 83.2%(7/10) | 94.0%(4/2) | 99.7% |
| achamo | XD | 100.0%(0/0) | 76.8%(23/0) | 82.7%(7/10) | 94.4%(6/0) | 100.0% |
| airmd | Colo | 100.0%(0/0) | 79.6%(20/0) | 82.3%(7/10) | 95.4%(5/0) | 99.9% |
| akami_m_a1 | XD | 92.2%(8/0) | 80.2%(16/3) | 86.8%(3/10) | 97.0%(2/1) | 73.6% |
| ametama | Colo | 100.0%(0/0) | 82.6%(17/0) | 82.9%(7/10) | 95.4%(5/0) | 100.0% |
| betbeton | Colo | 100.0%(0/0) | 63.1%(36/0) | 83.8%(6/10) | 94.0%(6/0) | 100.0% |
| blacky | Colo | 100.0%(0/0) | 82.3%(18/0) | 83.6%(6/10) | 95.8%(3/2) | 99.9% |
| bohmander | XD | 100.0%(0/0) | 79.6%(20/0) | 82.5%(7/10) | 94.5%(5/1) | 99.8% |
| booster | Colo | 100.0%(0/0) | 81.0%(19/0) | 82.5%(6/12) | 95.1%(5/0) | 100.0% |
| boss555_a1 | XD | 99.1%(1/0) | 81.2%(16/3) | 86.7%(4/10) | 97.3%(2/1) | 89.7% |
| cerebi | XD | 100.0%(0/0) | 62.4%(38/0) | 84.5%(5/11) | 93.3%(6/0) | 99.8% |
| cokodora | Colo | 93.4%(7/0) | 85.7%(14/0) | 83.5%(6/10) | 95.4%(4/0) | 88.9% |
| darklugia | XD | 100.0%(0/0) | 76.9%(23/0) | 83.1%(6/11) | 91.9%(7/1) | 99.9% |
| denryu | Colo | 100.0%(0/0) | 83.2%(16/0) | 82.8%(7/11) | 92.1%(5/3) | 99.9% |
| deoxys | XD | 100.0%(0/0) | 64.9%(35/0) | 83.2%(7/10) | 92.5%(6/1) | 99.6% |
| dirteng | Colo | 100.0%(0/0) | 80.8%(19/0) | 82.8%(7/11) | 94.9%(5/0) | 99.9% |
| donmel | Colo | 92.9%(7/0) | 83.8%(16/0) | 84.2%(5/11) | 95.6%(2/2) | 87.3% |
| ebiwalar | Colo | 91.7%(8/0) | 78.9%(21/0) | 83.1%(6/11) | 95.4%(4/0) | 83.0% |
| eievui | Colo | 100.0%(0/0) | 59.6%(40/0) | 83.3%(7/10) | 97.4%(2/0) | 99.9% |
| eifie | Colo | 100.0%(0/0) | 65.2%(35/0) | 83.7%(6/10) | 92.5%(5/3) | 99.9% |
| entei | Colo | 100.0%(0/0) | 85.1%(15/0) | 83.1%(7/10) | 94.3%(4/1) | 99.8% |
| fire | Colo | 99.7%(0/0) | 85.1%(14/1) | 83.1%(6/11) | 94.8%(4/2) | 99.7% |
| freezer | Colo | 100.0%(0/0) | 82.2%(17/1) | 81.2%(6/12) | 95.1%(5/0) | 100.0% |
| frygon | XD | 100.0%(0/0) | 80.8%(19/0) | 82.6%(6/11) | 93.3%(5/2) | 99.9% |
| fushigibana | Colo | 100.0%(0/0) | 82.4%(18/0) | 82.8%(7/10) | 96.4%(3/1) | 99.9% |
| gaderi_0101 | XD | 92.0%(8/0) | 76.3%(22/1) | 83.9%(2/14) | 98.0%(1/1) | 84.6% |
| gallop | XD | 100.0%(0/0) | 77.9%(22/0) | 83.4%(6/11) | 95.4%(3/1) | 99.7% |
| gangar | Colo | 100.0%(0/0) | 62.8%(37/0) | 81.8%(7/12) | 97.5%(2/0) | 100.0% |
| gba_emr_f_0101 | XD | 93.0%(7/0) | 79.7%(15/6) | 84.2%(2/14) | 97.7%(1/1) | 80.2% |
| ghos | Colo | 99.7%(0/0) | 63.8%(34/2) | 84.6%(5/11) | 92.5%(6/1) | 99.6% |
| gonyonyo | Colo | 100.0%(0/0) | 79.6%(20/0) | 82.9%(7/10) | 94.8%(4/1) | 99.8% |
| groudon | Colo | 99.9%(0/0) | 85.0%(15/0) | 82.4%(7/10) | 88.1%(6/6) | 99.7% |
| haganeil | XD | 100.0%(0/0) | 85.3%(15/0) | 79.8%(8/12) | 96.5%(3/0) | 100.0% |
| hakuryu | Colo | 100.0%(0/0) | 84.1%(16/0) | 84.0%(5/11) | 98.0%(2/0) | 99.9% |
| hassam | Colo | 100.0%(0/0) | 84.7%(15/0) | 83.5%(6/10) | 93.7%(6/1) | 99.9% |
| heracros | Colo | 100.0%(0/0) | 83.4%(17/0) | 83.0%(7/10) | 94.9%(5/0) | 99.9% |
| hinoarashi | Colo | 100.0%(0/0) | 66.3%(34/0) | 84.6%(7/9) | 94.9%(4/1) | 99.9% |
| hizuki_a1 | Colo | 99.7%(0/0) | 83.0%(15/2) | 85.4%(5/10) | 97.5%(2/1) | 72.6% |
| hizuki_b1 | Colo | 91.0%(9/0) | 79.5%(20/1) | 85.1%(5/10) | 97.9%(1/1) | 80.7% |
| houou | Colo | 100.0%(0/0) | 76.2%(24/0) | 80.2%(6/13) | 92.3%(8/0) | 100.0% |
| kairiky | Colo | 100.0%(0/0) | 61.1%(39/0) | 83.9%(6/10) | 96.2%(4/0) | 99.9% |
| kairyu | Colo | 100.0%(0/0) | 80.4%(20/0) | 82.5%(4/14) | 97.1%(3/0) | 99.9% |
| kemusso | Colo | 100.0%(0/0) | 88.9%(11/0) | 82.9%(6/11) | 93.2%(5/2) | 99.7% |
| kibanha | XD | 100.0%(0/0) | 76.2%(24/0) | 82.6%(7/11) | 94.3%(6/0) | 99.8% |
| kirlia | Colo | 100.0%(0/0) | 86.6%(13/0) | 83.9%(6/10) | 96.8%(2/1) | 99.8% |
| koduck | Colo | 100.0%(0/0) | 83.3%(17/0) | 82.9%(7/10) | 92.9%(5/2) | 99.7% |
| kyukon | Colo | 100.0%(0/0) | 72.1%(28/0) | 83.3%(6/11) | 94.4%(5/0) | 99.7% |
| lantern | Colo | 99.3%(1/0) | 82.4%(14/4) | 83.6%(6/11) | 94.1%(4/2) | 99.3% |
| laplace | Colo | 100.0%(0/0) | 63.4%(37/0) | 84.0%(5/11) | 95.3%(3/2) | 99.9% |
| lizardon | Colo | 100.0%(0/0) | 81.2%(19/0) | 81.4%(5/13) | 94.3%(6/0) | 99.9% |
| mage_0101 | XD | 91.8%(8/0) | 78.2%(20/1) | 84.5%(2/14) | 98.0%(1/1) | 84.5% |
| mcgroudon_1101 | XD | 91.6%(8/0) | 81.6%(16/2) | 83.5%(3/14) | 96.9%(3/0) | 83.2% |
| metamon | Colo | 100.0%(0/0) | 53.4%(47/0) | 84.7%(5/10) | 97.6%(2/0) | 99.9% |
| miniryu | XD | 100.0%(0/0) | 59.4%(41/0) | 84.6%(5/10) | 98.1%(2/0) | 99.9% |
| mirrabo_0101 | XD | 91.8%(8/0) | 80.1%(18/2) | 84.2%(2/14) | 97.6%(2/1) | 86.4% |
| nendoll | Colo | 100.0%(0/0) | 77.4%(20/3) | 83.5%(6/11) | 92.0%(2/6) | 99.5% |
| noctus | Colo | 100.0%(0/0) | 81.5%(18/0) | 82.9%(6/11) | 91.8%(6/2) | 99.8% |
| nukenin | XD | 97.1%(3/0) | 91.8%(8/0) | 83.6%(5/11) | 96.9%(2/1) | 94.9% |
| nyoromo | Colo | 100.0%(0/0) | 70.1%(30/0) | 82.8%(6/11) | 94.6%(5/0) | 99.9% |
| patcheel | Colo | 100.0%(0/0) | 74.4%(26/0) | 82.6%(7/10) | 95.0%(4/1) | 100.0% |
| pikachu | Colo | 100.0%(0/0) | 78.6%(21/0) | 82.1%(5/13) | 96.1%(4/0) | 99.9% |
| rayquaza | XD | 100.0%(0/0) | 86.1%(14/0) | 83.5%(7/10) | 92.0%(7/1) | 99.4% |
| rinto_0101 | XD | 93.7%(6/0) | 80.1%(13/7) | 84.5%(2/14) | 97.8%(1/1) | 82.3% |
| rinto_1101 | XD | 93.9%(6/0) | 77.5%(13/10) | 84.8%(2/13) | 98.0%(1/1) | 84.5% |
| rinto_1102 | XD | 94.3%(6/0) | 78.9%(12/9) | 84.8%(2/13) | 98.0%(1/1) | 86.3% |
| roselia | Colo | 100.0%(0/0) | 71.7%(28/0) | 84.0%(5/11) | 94.3%(4/2) | 99.9% |
| ruffresia | Colo | 100.0%(0/0) | 60.8%(39/0) | 84.0%(5/11) | 97.6%(2/0) | 100.0% |
| runpappa | XD | 100.0%(0/0) | 76.1%(24/0) | 83.2%(7/10) | 94.9%(5/0) | 99.8% |
| showers | Colo | 100.0%(0/0) | 63.7%(36/0) | 83.3%(6/11) | 98.5%(1/0) | 100.0% |
| sirnight | Colo | 100.0%(0/0) | 75.9%(24/0) | 83.2%(6/11) | 95.4%(5/0) | 99.7% |
| subame | Colo | 100.0%(0/0) | 78.3%(22/0) | 84.0%(6/10) | 96.7%(3/0) | 99.8% |
| suikun | Colo | 100.0%(0/0) | 82.2%(18/0) | 82.1%(7/11) | 92.7%(7/0) | 99.9% |
| sunnygo | Colo | 100.0%(0/0) | 91.9%(8/0) | 84.3%(5/10) | 92.4%(2/5) | 99.9% |
| thunder | Colo | 100.0%(0/0) | 62.4%(38/0) | 84.3%(5/10) | 94.8%(5/0) | 99.7% |
| tropius | Colo | 100.0%(0/0) | 81.9%(18/0) | 82.4%(7/10) | 95.2%(4/0) | 99.8% |
| usohachi | XD | 92.3%(8/0) | 72.4%(22/6) | 85.8%(4/10) | 94.9%(5/0) | 81.8% |
| vibrava | Colo | 100.0%(0/0) | 78.4%(22/0) | 83.3%(7/10) | 95.1%(5/0) | 100.0% |

**Averages:** NBN 98.6% · NIN 77.0% · BBB 83.4% · IBI 95.2% · BNB 96.3%

### Map / Scene Models

| Model | Game | NBN ✅ | NIN 🟠 | BBB | IBI ✅ | BNB ✅ |
|---|---|---|---|---|---|---|
| D1_out | XD | 99.3%(1/0) | 25.1%(0/75) | — | 96.2%(4/0) | 99.2% |
| D2_rest_1 | XD | 98.7%(1/0) | 25.3%(0/74) | 78.6%(3/19) | 96.1%(2/1) | 99.4% |
| D6_out_all | XD | 96.4%(4/0) | 18.1%(0/82) | 72.5%(7/21) | 93.7%(5/1) | 92.9% |
| M1_out | XD | 98.3%(2/0) | 23.1%(0/77) | 84.6%(3/13) | 96.8%(3/1) | 97.7% |
| M2_out | XD | 99.4%(1/0) | 25.0%(0/75) | 82.7%(3/14) | 96.3%(3/1) | 98.6% |
| M3_out | XD | 99.2%(1/0) | 23.1%(0/77) | 81.7%(3/15) | 97.0%(3/0) | 93.7% |
| M3_shrine_1F | XD | 99.9%(0/0) | 24.2%(0/76) | 81.4%(2/17) | 95.1%(5/0) | 95.4% |

**Averages:** NBN 98.7% · NIN 23.4% · BBB n/a (skipped this sweep) · IBI 95.9% · BNB 96.7%

<!-- AUTO-GENERATED-RESULTS END -->

### Per-category breakdown (averaged across the corpus)

#### BBB

| Category | Match | Error | Miss | Models |
|---|---|---|---|---|
| actions | 13.4% | 18.9% | 67.7% | 79 |
| bones | 94.6% | 5.4% | 0.0% | 79 |
| cameras | 100.0% | 0.0% | 0.0% | 79 |
| constraints | 98.3% | 1.7% | 0.0% | 14 |
| lights | 100.0% | 0.0% | 0.0% | 79 |
| materials | 93.0% | 7.0% | 0.0% | 79 |
| meshes | 97.4% | 2.4% | 0.2% | 79 |

#### IBI

| Category | Match | Error | Miss | Models |
|---|---|---|---|---|
| animations | 100.0% | 0.0% | 0.0% | 86 |
| bones | 80.8% | 15.3% | 4.0% | 86 |
| cameras | 100.0% | 0.0% | 0.0% | 86 |
| constraints | 100.0% | 0.0% | 0.0% | 16 |
| lights | 100.0% | 0.0% | 0.0% | 86 |
| materials | 90.5% | 7.8% | 1.6% | 86 |
| meshes | 100.0% | 0.0% | 0.0% | 86 |

---

## How Scores Are Computed

All scores are displayed as **`match%(error/miss)`** where:
- **match** — percentage of fields that round-tripped correctly
- **error** — percentage of fields that existed in both but had different values (implementation bugs or inherent limitations)
- **miss** — percentage of fields that existed in the original but were missing/None in the round-tripped result (not yet implemented)

Scoring methods:
- **BNB**: Fuzzy 4-byte word matching — splits both binaries into words, counts matches by value (not position). All non-matches are errors (layout differences).
- **NBN**: Recursively compares all node fields after serialize → reparse. Distinguishes errors (value mismatch) from misses (missing node/field).
- **NIN**: Walks the full original node tree as the denominator. Missing subtrees in the composed output count as misses; differing values count as errors.
- **BBB**: Per-category dataclass field comparison between the importer-produced BR (`importer.plan` output) and the exporter-recovered BR (`exporter.describe` of the same scene after `build_blender`). Categories: bones, meshes, materials, actions, lights, cameras. Same skip-list as IBI.
- **IBI**: Pure Plan round-trip (importer IR→BR → exporter BR→IR, no bpy leg). Category-weighted scoring. Each IR category (bones, meshes, materials, animations, constraints, lights, cameras) is scored independently, then averaged across categories that have data. Empty categories are excluded.

---

## How to Run Round-Trip Tests

All five test types (NBN, NIN, BBB, IBI, BNB) are run via a single script that operates on real model files. Requires Python 3.11 with `bpy==4.5.7` (see README for install instructions).

```bash
# Single model
python3.11 tests/round_trip/run_round_trips.py ~/Documents/Projects/DAT\ plugin/models/nukenin.pkx

# Multiple models
python3.11 tests/round_trip/run_round_trips.py model1.pkx model2.pkx

# All models in a directory
python3.11 tests/round_trip/run_round_trips.py ~/Documents/Projects/DAT\ plugin/models/

# Verbose output (shows NIN and IBI mismatch details)
python3.11 tests/round_trip/run_round_trips.py ~/Documents/Projects/DAT\ plugin/models/nukenin.pkx -v
```

Synthetic round-trip tests (no game files needed) also run as part of the main pytest suite:

```bash
python3 -m pytest tests/test_write_roundtrip.py -v
```

---

### Limiting Factors by Test Type

**IBI / BBB animations** — animation accuracy is the largest drag on both IBI and BBB scores. The build → describe round-trip writes per-frame pose-basis fcurves into Blender pose bones, then samples them back via the inverse pose-basis formula and Bezier-sparsifies the result. Each leg is lossy: floating-point precision in pose-basis matrix math, sparsifier deciding "this Bezier curve approximates these samples within tolerance" (so fewer keyframes come out than went in), Euler decomposition ambiguity (multiple Euler triples encode the same rotation), and minor differences between Blender's interpolator and our re-sampler. Some loss is inherent to the round-trip; the rest is real fidelity bugs worth chasing.

**BBB materials** — even with id fields skipped, BRMaterial scores are dragged down by structural drift between the importer's plan-time `BRNodeGraph` and the BRNodeGraph the exporter's describe reads back from Blender. The graphs are functionally equivalent (both produce the same `IRMaterial` when run through `plan_material`) but Blender adds, renames, or collapses nodes during build (auto-added `ShaderNodeOutputMaterial`, `.001` suffix collisions, default-value socket serialisation). A graph-equivalence comparator would close most of the remaining gap; a naive dataclass diff overcounts.

**NIN** — The largest NIN error sources are (measured by categorising verbose errors on the lowest-scoring models):

1. **Display-list chunking** — the dominant contributor (~10–11 mismatched fields per model). Compose emits raw `TRIANGLES`, producing roughly 2× the chunk count of the originals (`display_list_chunk_count: 47 vs 86`, `111 vs 203`). Originals use ~80% tri-strips / ~12% quads / ~8% triangles. Encoding display lists as TRI_STRIP+QUADS+TRIANGLES is the highest-leverage remaining NIN optimization.
2. **Palette C8 re-encoding** — the palette **format** now round-trips: the IR carries a `palette_format_override` (mirroring the image `gx_format_override`), read from the original TLUT format at import, surfaced as `bpy_image.dat_palette_format`, and honored by the C4/C8/C14X2 encoders. The remaining `entry_count`/`data` divergence (e.g. `entry_count: 250 vs 98`) is an accepted mismatch: the original TLUT allocated unused/duplicate slots that can't be recovered from the decoded RGBA, and the 98-unique-color palette renders identically.
3. **Vertex attribute descriptors** — `attribute_type`, `component_count`, `stride`, `frac_value` layout differences.

Material **colors are NOT a current error source.** The value path is lossless (u8 `n` → float `n/255` on parse → `int(n/255*255 + 0.5) = n` on compose), and the comparator's `_color_channel_equiv` guard (added in c51fcac) tolerates the float[0-1]-vs-u8[0-255] scale difference with a ±1-step margin. Verified: 0 color-field mismatches on `metamon`/`eievui`/`miniryu`.

Other notes: the compose phase encodes BEZIER keyframes as HSD_A_OP_SPL with slopes, sets start_frame from the first keyframe, and uses optimal quantization format selection (Colo/XD formula: `frac_bits = type_bits - ceil(log2(max_abs + 1))`). Material animations composed (color/alpha + texture UV). Structural parity is solid: DObject grouping, PObject chaining, vertex descriptors, flags, and texture format selection all match.

**NBN** — Pointer resolution edge cases and alignment differences in DATBuilder. Functionally correct (field values match).

**BNB** — Layout differences from DATBuilder's node ordering and alignment conventions vs the original HAL DAT compiler.
