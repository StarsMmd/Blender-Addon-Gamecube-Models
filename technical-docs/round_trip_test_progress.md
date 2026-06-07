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

### IR → Blender → IR (IBI)

Plan IR → BR via the importer's plan, build into Blender via the importer's build, then run the exporter's `describe → plan` phases to recover a new IRScene. Compare the two IR scenes using category-weighted scoring — each IR category (bones, meshes, materials, animations, constraints, lights) is scored independently, then averaged across categories that have data. This prevents large vertex arrays from inflating the score. IBI is broader than BBB: it adds the IR→BR and BR→IR conversion steps on either side of the bpy round-trip.

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

**Overall export pipeline completion (76 character/Pokémon models): 🔵 80.0%** _(weighted: NBN 20% × 92.3 + NIN 35% × 76.2 + BBB 15% × 82.1 + IBI 25% × 73.3 + BNB 5% × 85.4)_

_Average health: 🔴 0-20% · 🟠 21-40% · 🟡 41-60% · 🔵 61-80% · ✅ 81-100%_

Scores below come from the full corpus in `~/Documents/Projects/DAT plugin/models/`, run with `python3.11` and `bpy==4.5.7`. All scores displayed as `match%(error/miss)` — see "How Scores Are Computed" for definitions.

> **Note on map results.** The map / scene corpus (six `.rdat` files) takes 5–20 min per model on the slower entries; the table below shows whichever maps had completed at the time the doc was last refreshed. A full sweep of the maps is a separate batch invocation. `D1_out.rdat` is excluded — it hangs the runner. Re-generate via `python3 tools/parse_rt_results.py <runner-output>`.

<!-- AUTO-GENERATED-RESULTS START -->

### Character / Pokémon Models

| Model | Game | NBN ✅ | NIN 🔵 | BBB ✅ | IBI 🔵 | BNB ✅ |
|---|---|---|---|---|---|---|
| absol | Colo | 92.3%(8/0) | 78.7%(21/0) | 82.2%(12/6) | 63.2%(15/21) | 86.4% |
| achamo | XD | 92.0%(8/0) | 76.2%(24/0) | 81.6%(11/7) | 73.5%(15/11) | 84.3% |
| airmd | Colo | 92.8%(7/0) | 79.3%(21/0) | 81.3%(12/7) | 72.2%(15/13) | 85.0% |
| akami_m_a1 | XD | 92.2%(8/0) | 79.9%(17/3) | 83.5%(7/10) | 68.9%(6/25) | 74.3% |
| ametama | Colo | 93.1%(7/0) | 82.1%(18/0) | 81.9%(12/6) | 78.8%(15/7) | 90.2% |
| betbeton | Colo | 90.0%(10/0) | 62.7%(37/0) | 82.6%(10/7) | 70.0%(13/17) | 82.0% |
| blacky | Colo | 93.2%(7/0) | 81.9%(18/0) | 82.5%(11/7) | 72.4%(13/15) | 88.6% |
| bohmander | XD | 91.5%(9/0) | 79.0%(21/0) | 81.4%(12/7) | 68.9%(14/17) | 84.1% |
| booster | Colo | 92.9%(7/0) | 80.1%(20/0) | 81.2%(11/8) | 79.7%(12/9) | 91.5% |
| boss555_a1 | XD | 92.4%(8/0) | 80.7%(17/3) | 83.3%(7/10) | 75.2%(8/17) | 83.1% |
| cerebi | XD | 89.6%(10/0) | 61.9%(38/0) | 83.0%(8/9) | 74.7%(14/12) | 82.0% |
| cokodora | Colo | 93.4%(7/0) | 84.6%(15/0) | 82.4%(10/7) | 60.2%(12/28) | 86.4% |
| darklugia | XD | 90.7%(9/0) | 76.6%(23/0) | 81.8%(10/8) | 63.6%(14/22) | 82.0% |
| denryu | Colo | 93.9%(6/0) | 82.3%(17/0) | 81.5%(11/8) | 72.8%(15/12) | 87.3% |
| deoxys | XD | 90.7%(9/0) | 64.2%(36/0) | 82.2%(12/6) | 66.8%(18/15) | 84.5% |
| dirteng | Colo | 91.3%(9/0) | 80.2%(20/0) | 81.5%(10/8) | 74.0%(15/11) | 82.6% |
| donmel | Colo | 92.9%(7/0) | 82.6%(17/0) | 82.9%(9/8) | 69.6%(11/19) | 85.7% |
| ebiwalar | Colo | 91.7%(8/0) | 78.2%(22/0) | 81.8%(10/8) | 78.1%(14/8) | 82.6% |
| eievui | Colo | 89.8%(10/0) | 59.2%(41/0) | 82.7%(11/6) | 77.3%(12/11) | 82.8% |
| eifie | Colo | 91.1%(9/0) | 64.6%(35/0) | 82.5%(10/7) | 71.2%(14/15) | 82.5% |
| entei | Colo | 93.4%(7/0) | 84.3%(16/0) | 81.8%(12/7) | 70.4%(16/14) | 85.5% |
| fire | Colo | 93.3%(7/0) | 84.6%(15/1) | 81.6%(11/8) | 81.3%(11/7) | 83.5% |
| freezer | Colo | 93.1%(7/0) | 81.3%(18/1) | 80.1%(11/9) | 80.6%(12/8) | 90.5% |
| frygon | XD | 93.0%(7/0) | 80.0%(20/0) | 81.2%(11/8) | 71.3%(15/14) | 86.0% |
| fushigibana | Colo | 92.7%(7/0) | 81.5%(18/0) | 81.7%(13/6) | 71.4%(14/15) | 89.1% |
| gaderi_0101 | XD | 92.0%(8/0) | 75.1%(23/1) | 81.9%(4/14) | 67.9%(2/30) | 83.8% |
| gallop | XD | 91.7%(8/0) | 77.4%(23/0) | 82.0%(10/8) | 68.9%(12/19) | 83.2% |
| gangar | Colo | 90.0%(10/0) | 62.4%(38/0) | 80.6%(10/9) | 76.3%(9/15) | 83.6% |
| gba_emr_f_0101 | XD | 93.0%(7/0) | 79.3%(15/6) | 82.1%(4/14) | 67.8%(2/31) | 80.0% |
| ghos | Colo | 90.3%(10/0) | 63.1%(35/2) | 82.5%(8/10) | 79.6%(11/9) | 79.2% |
| gonyonyo | Colo | 94.4%(6/0) | 77.8%(22/0) | 81.9%(12/6) | 77.1%(13/10) | 87.7% |
| groudon | Colo | 94.3%(6/0) | 83.9%(16/0) | 81.3%(12/6) | 72.6%(16/11) | 91.7% |
| haganeil | XD | 92.7%(7/0) | 84.3%(16/0) | 79.0%(13/8) | 81.8%(11/7) | 92.7% |
| hakuryu | Colo | 93.6%(6/0) | 83.1%(17/0) | 82.6%(8/9) | 77.8%(11/11) | 87.2% |
| hassam | Colo | 93.0%(7/0) | 84.0%(16/0) | 82.1%(11/7) | 77.0%(14/9) | 86.2% |
| heracros | Colo | 93.0%(7/0) | 82.7%(17/0) | 81.8%(11/7) | 83.4%(13/4) | 83.9% |
| hinoarashi | Colo | 90.3%(10/0) | 65.8%(34/0) | 83.5%(10/7) | 75.4%(14/11) | 88.1% |
| hizuki_a1 | Colo | 92.5%(7/0) | 82.6%(16/2) | 83.4%(7/10) | 75.3%(6/19) | 66.7% |
| houou | Colo | 92.5%(7/0) | 75.3%(25/0) | 78.6%(11/10) | 68.2%(18/14) | 87.8% |
| kairiky | Colo | 89.9%(10/0) | 60.4%(40/0) | 82.8%(9/8) | 80.1%(10/10) | 80.9% |
| kairyu | Colo | 92.7%(7/0) | 79.6%(20/0) | 81.2%(8/11) | 66.6%(9/24) | 92.1% |
| kemusso | Colo | 94.9%(5/0) | 86.9%(13/0) | 81.5%(9/10) | 78.2%(11/11) | 85.1% |
| kibanha | XD | 92.0%(8/0) | 75.3%(25/0) | 81.2%(10/8) | 79.2%(14/7) | 85.6% |
| kirlia | Colo | 93.2%(7/0) | 85.9%(14/0) | 82.8%(10/7) | 70.7%(13/17) | 86.9% |
| koduck | Colo | 94.0%(6/0) | 82.4%(18/0) | 81.8%(12/7) | 66.7%(14/19) | 85.6% |
| kyukon | Colo | 90.9%(9/0) | 71.5%(29/0) | 82.0%(10/8) | 67.8%(13/19) | 81.1% |
| lantern | Colo | 93.6%(6/0) | 81.5%(15/4) | 81.8%(10/8) | 72.9%(14/13) | 88.8% |
| laplace | Colo | 90.9%(9/0) | 62.7%(37/0) | 82.4%(8/10) | 81.0%(7/12) | 83.0% |
| lizardon | Colo | 93.5%(7/0) | 80.3%(19/0) | 79.9%(9/11) | 73.7%(11/16) | 92.3% |
| mage_0101 | XD | 91.8%(8/0) | 77.6%(21/1) | 82.4%(4/14) | 65.1%(2/33) | 83.3% |
| mcgroudon_1101 | XD | 91.6%(8/0) | 80.6%(17/2) | 81.1%(5/14) | 66.5%(4/30) | 82.6% |
| metamon | Colo | 89.0%(11/0) | 53.1%(47/0) | 84.0%(8/8) | 83.1%(7/10) | 81.4% |
| miniryu | XD | 90.2%(10/0) | 58.5%(41/0) | 83.8%(9/7) | 77.2%(9/14) | 81.6% |
| mirrabo_0101 | XD | 91.8%(8/0) | 79.7%(19/2) | 82.1%(4/14) | 64.4%(2/33) | 85.9% |
| nendoll | Colo | 93.4%(7/0) | 75.9%(21/3) | 83.2%(11/6) | 82.2%(10/8) | 94.4% |
| noctus | Colo | 93.2%(7/0) | 80.9%(19/0) | 81.3%(10/9) | 63.0%(15/22) | 83.2% |
| nukenin | XD | 97.1%(3/0) | 87.6%(12/0) | 82.0%(9/9) | 83.9%(11/6) | 95.0% |
| nyoromo | Colo | 91.4%(9/0) | 69.5%(31/0) | 81.6%(12/7) | 74.0%(15/11) | 89.8% |
| patcheel | Colo | 92.4%(8/0) | 73.7%(26/0) | 81.7%(13/5) | 70.0%(15/15) | 92.8% |
| pikachu | Colo | 93.4%(7/0) | 77.8%(22/0) | 80.8%(9/10) | 69.3%(10/21) | 90.9% |
| rayquaza | XD | 93.6%(6/0) | 84.3%(16/0) | 83.2%(14/3) | 79.8%(17/4) | 92.2% |
| rinto_0101 | XD | 93.7%(6/0) | 79.5%(14/7) | 82.5%(4/14) | 63.3%(1/35) | 80.1% |
| rinto_1101 | XD | 93.9%(6/0) | 76.3%(14/10) | 82.8%(4/13) | 66.8%(2/31) | 83.3% |
| rinto_1102 | XD | 94.3%(6/0) | 77.5%(14/9) | 82.7%(4/13) | 66.4%(2/32) | 84.9% |
| roselia | Colo | 91.0%(9/0) | 71.1%(29/0) | 82.4%(9/8) | 73.5%(13/13) | 87.4% |
| ruffresia | Colo | 90.2%(10/0) | 60.3%(40/0) | 82.9%(8/9) | 77.7%(8/14) | 85.5% |
| runpappa | XD | 92.5%(7/0) | 75.2%(25/0) | 82.5%(13/5) | 74.4%(16/9) | 85.2% |
| showers | Colo | 89.7%(10/0) | 63.4%(37/0) | 82.6%(10/7) | 73.9%(9/18) | 81.2% |
| sirnight | Colo | 92.2%(8/0) | 75.0%(25/0) | 81.9%(10/8) | 70.2%(14/16) | 84.2% |
| subame | Colo | 91.7%(8/0) | 77.4%(23/0) | 82.9%(10/7) | 75.8%(13/11) | 82.0% |
| suikun | Colo | 92.2%(8/0) | 81.2%(19/0) | 81.2%(13/6) | 66.8%(19/14) | 89.8% |
| sunnygo | Colo | 97.4%(3/0) | 89.6%(10/0) | 83.0%(9/8) | 82.9%(9/8) | 93.7% |
| thunder | Colo | 89.7%(10/0) | 61.8%(38/0) | 82.7%(8/9) | 80.4%(11/9) | 80.1% |
| tropius | Colo | 92.9%(7/0) | 81.4%(19/0) | 81.0%(11/8) | 64.8%(14/21) | 83.5% |
| usohachi | XD | 92.3%(8/0) | 71.8%(22/6) | 84.1%(7/9) | 87.8%(9/3) | 81.7% |
| vibrava | Colo | 91.6%(8/0) | 77.9%(22/0) | 82.8%(12/5) | 74.2%(16/10) | 86.8% |

**Averages (76 models):** NBN 92.3% · NIN 76.2% · BBB 82.1% · IBI 73.3% · BNB 85.4%

### Map / Scene Models

| Model | Game | NBN ✅ | NIN 🔴 | BBB 🔵 | IBI 🔵 | BNB 🔴 |
|---|---|---|---|---|---|---|
| D2_rest_1 | XD | 98.7%(1/0) | 25.0%(1/74) | 72.7%(9/19) | 75.6%(8/16) | 6.4% |
| D6_out_all | XD | 96.4%(4/0) | 18.1%(0/82) | 68.1%(13/19) | 61.2%(14/25) | 43.7% |
| M1_out | XD | 98.3%(2/0) | 23.1%(0/77) | 79.4%(8/12) | 78.0%(9/13) | 2.6% |
| M2_out | XD | 99.4%(1/0) | 25.0%(0/75) | 77.0%(9/14) | 79.2%(10/11) | 3.0% |
| M3_out | XD | 99.2%(1/0) | 23.0%(0/77) | 76.3%(9/15) | 79.8%(9/11) | 1.5% |
| M3_shrine_1F | XD | 99.9%(0/0) | 24.2%(0/76) | 75.5%(8/17) | 75.0%(8/17) | 0.8% |

**Averages (6 models):** NBN 98.7% · NIN 23.1% · BBB 74.9% · IBI 74.8% · BNB 9.7%

<!-- AUTO-GENERATED-RESULTS END -->

### Per-category breakdown (averaged across the corpus)

#### BBB

| Category | Match | Error | Miss | Models |
|---|---|---|---|---|
| actions | 19.3% | 28.5% | 52.2% | 77 |
| bones | 94.5% | 5.5% | 0.0% | 77 |
| cameras | 99.9% | 0.1% | 0.0% | 77 |
| constraints | 97.4% | 2.6% | 0.0% | 13 |
| lights | 80.4% | 19.6% | 0.0% | 77 |
| materials | 78.5% | 21.5% | 0.0% | 77 |
| meshes | 96.6% | 2.5% | 0.8% | 77 |

#### IBI

| Category | Match | Error | Miss | Models |
|---|---|---|---|---|
| animations | 36.5% | 40.4% | 23.1% | 77 |
| bones | 79.3% | 16.3% | 4.4% | 77 |
| cameras | 99.9% | 0.1% | 0.0% | 77 |
| constraints | 97.4% | 2.6% | 0.0% | 13 |
| lights | 78.4% | 21.6% | 0.0% | 77 |
| materials | 68.8% | 4.4% | 26.8% | 77 |
| meshes | 50.6% | 7.9% | 41.6% | 77 |

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
- **IBI**: Category-weighted scoring. Each IR category (bones, meshes, materials, animations, constraints, lights, cameras) is scored independently, then averaged across categories that have data. Empty categories are excluded.

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

**NIN** — Material color normalization is the largest NIN error source: the IR stores colors as normalized floats [0-1] while original nodes use raw u8 [0-255], causing mismatches on ambient/diffuse/specular RGBA fields across all materials. The compose phase encodes BEZIER keyframes as HSD_A_OP_SPL with slopes, sets start_frame from the first keyframe, and uses optimal quantization format selection (Colo/XD formula: `frac_bits = type_bits - ceil(log2(max_abs + 1))`). Display list chunk count differences are minor (1 field per PObject). Palette data differences from C8 re-encoding. Material animations composed (color/alpha + texture UV). Structural parity is solid: DObject grouping, PObject chaining, vertex descriptors, flags, and texture format selection all match. Future optimization: encode display lists as TRI_STRIP+QUADS+TRIANGLES (originals use ~80% strips, ~12% quads, ~8% triangles).

**NBN** — Pointer resolution edge cases and alignment differences in DATBuilder. Functionally correct (field values match).

**BNB** — Layout differences from DATBuilder's node ordering and alignment conventions vs the original HAL DAT compiler.
