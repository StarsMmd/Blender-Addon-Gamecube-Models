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

Parse a DAT binary, write it back, and compare the output bytes against the input using a fuzzy 4-byte word matching algorithm. This measures binary-level fidelity — whether the output file would be byte-identical to the input. Exact 1:1 binary matches are a stretch goal that will require matching the original SysDolphin compiler's layout conventions (alignment, node ordering, padding). A high BNB score is purely aesthetic — it has no functional benefit. NBN determines the practical accuracy of the exporter.

### What round-trips deliberately ignore

The comparators skip these field categories so the score reflects model data, not pipeline plumbing:

- **Pre-computed matrices** derived from SRT — `world_matrix`, `local_matrix`, `normalized_world_matrix`, `normalized_local_matrix`, `scale_correction`, `accumulated_scale`. They're cached convenience fields, not independent data.
- **Pre-computed deformed geometry** — `deformed_vertices`, `deformed_normals`. Derived from bone weights + vertices.
- **DAT file offsets** used as cache keys — `image_id`, `palette_id`. Per-file binary identifiers, not model content.
- **Internal opaque ids** — `id` (IRMesh / BRMesh foreign-key target), `cache_key`, `dedup_key`, `material_mesh_name`. These are pipeline-internal cross-references; the importer and exporter mint them independently for their own binding purposes, and identity across a build → describe round-trip isn't a fidelity concern.

---

## Test Results

**Overall export pipeline completion (76 character/Pokémon models): 🔵 78.4%** _(weighted: NBN 20% × 92.3 + NIN 35% × 76.2 + BBB 15% × 78.9 + IBI 25% × 69.9 + BNB 5% × 79.0)_

_Average health: 🔴 0-20% · 🟠 21-40% · 🟡 41-60% · 🔵 61-80% · ✅ 81-100%_

Scores below come from the full corpus in `~/Documents/Projects/DAT plugin/models/`, run with `python3.11` and `bpy==4.5.7`. All scores displayed as `match%(error/miss)` — see "How Scores Are Computed" for definitions.

> **Note on map results.** The map / scene corpus (six `.rdat` files) takes 5–20 min per model on the slower entries; the table below shows whichever maps had completed at the time the doc was last refreshed. A full sweep of the maps is a separate batch invocation. `D1_out.rdat` is excluded — it hangs the runner. Re-generate via `python3 tools/parse_rt_results.py <runner-output>`.

<!-- AUTO-GENERATED-RESULTS START -->

### Character / Pokémon Models

| Model | Game | NBN ✅ | NIN 🔵 | BBB 🔵 | IBI 🔵 | BNB 🔵 |
|---|---|---|---|---|---|---|
| absol | Colo | 92.3%(8/0) | 78.7%(21/0) | 78.8%(15/6) | 59.5%(19/21) | 84.5% |
| achamo | XD | 92.0%(8/0) | 76.2%(24/0) | 78.3%(14/7) | 69.9%(19/11) | 80.9% |
| airmd | Colo | 92.8%(7/0) | 79.3%(21/0) | 78.0%(15/7) | 68.6%(18/13) | 84.6% |
| akami_m_a1 | XD | 92.2%(8/0) | 79.9%(17/3) | 80.6%(9/10) | 65.8%(9/25) | 61.8% |
| ametama | Colo | 93.1%(7/0) | 82.1%(18/0) | 78.9%(16/6) | 75.4%(18/7) | 87.8% |
| betbeton | Colo | 90.0%(10/0) | 62.7%(37/0) | 79.2%(14/7) | 66.4%(16/17) | 80.7% |
| blacky | Colo | 93.2%(7/0) | 81.9%(18/0) | 79.1%(14/7) | 68.7%(17/15) | 86.1% |
| bohmander | XD | 91.5%(9/0) | 79.0%(21/0) | 78.1%(15/7) | 65.2%(18/17) | 82.5% |
| booster | Colo | 92.9%(7/0) | 80.1%(20/0) | 77.8%(14/8) | 76.0%(15/9) | 90.7% |
| boss555_a1 | XD | 92.4%(8/0) | 80.7%(17/3) | 80.4%(10/10) | 72.1%(11/17) | 51.4% |
| cerebi | XD | 89.6%(10/0) | 61.9%(38/0) | 79.6%(11/9) | 71.0%(17/12) | 79.0% |
| cokodora | Colo | 93.4%(7/0) | 84.6%(15/0) | 80.0%(13/7) | 57.6%(15/28) | 84.3% |
| darklugia | XD | 90.7%(9/0) | 76.6%(23/0) | 78.4%(14/8) | 59.9%(18/22) | 81.8% |
| denryu | Colo | 93.9%(6/0) | 82.3%(17/0) | 78.2%(14/8) | 69.1%(19/12) | 84.4% |
| deoxys | XD | 90.7%(9/0) | 64.2%(36/0) | 78.9%(16/6) | 63.3%(22/15) | 81.8% |
| dirteng | Colo | 91.3%(9/0) | 80.2%(20/0) | 78.2%(14/8) | 70.4%(19/11) | 79.3% |
| donmel | Colo | 92.9%(7/0) | 82.6%(17/0) | 79.6%(12/8) | 65.9%(15/19) | 65.3% |
| ebiwalar | Colo | 91.7%(8/0) | 78.2%(22/0) | 78.5%(13/8) | 74.4%(18/8) | 81.4% |
| eievui | Colo | 89.8%(10/0) | 59.2%(41/0) | 79.4%(15/6) | 73.6%(15/11) | 82.0% |
| eifie | Colo | 91.1%(9/0) | 64.6%(35/0) | 79.2%(14/7) | 67.6%(17/15) | 80.8% |
| entei | Colo | 93.4%(7/0) | 84.3%(16/0) | 78.5%(15/7) | 66.7%(20/14) | 83.2% |
| fire | Colo | 93.3%(7/0) | 84.6%(15/1) | 78.2%(14/8) | 77.6%(15/7) | 81.1% |
| freezer | Colo | 93.1%(7/0) | 81.3%(18/1) | 76.7%(15/9) | 77.0%(15/8) | 89.9% |
| frygon | XD | 93.0%(7/0) | 80.0%(20/0) | 77.9%(14/8) | 67.7%(19/14) | 83.5% |
| fushigibana | Colo | 92.7%(7/0) | 81.5%(18/0) | 78.3%(16/6) | 67.7%(18/15) | 88.0% |
| gaderi_0101 | XD | 92.0%(8/0) | 75.1%(23/1) | 79.0%(7/14) | 64.8%(5/30) | 31.1% |
| gallop | XD | 91.7%(8/0) | 77.4%(23/0) | 78.6%(13/8) | 65.3%(15/19) | 77.3% |
| gangar | Colo | 90.0%(10/0) | 62.4%(38/0) | 77.2%(14/9) | 72.6%(13/15) | 81.9% |
| gba_emr_f_0101 | XD | 93.0%(7/0) | 79.3%(15/6) | 79.5%(7/14) | 65.0%(4/31) | 74.0% |
| ghos | Colo | 90.3%(10/0) | 63.1%(35/2) | 79.2%(11/10) | 76.0%(15/9) | 77.7% |
| gonyonyo | Colo | 94.4%(6/0) | 77.8%(22/0) | 78.5%(15/6) | 73.5%(17/10) | 81.5% |
| groudon | Colo | 94.3%(6/0) | 83.9%(16/0) | 78.7%(15/6) | 74.5%(19/6) | 71.0% |
| haganeil | XD | 92.7%(7/0) | 84.3%(16/0) | 75.7%(16/8) | 78.2%(15/7) | 91.8% |
| hakuryu | Colo | 93.6%(6/0) | 83.1%(17/0) | 79.3%(12/9) | 74.2%(15/11) | 85.0% |
| hassam | Colo | 93.0%(7/0) | 84.0%(16/0) | 78.8%(14/7) | 73.3%(17/9) | 82.4% |
| heracros | Colo | 93.0%(7/0) | 82.7%(17/0) | 78.4%(14/7) | 79.8%(17/4) | 80.5% |
| hinoarashi | Colo | 90.3%(10/0) | 65.8%(34/0) | 80.2%(13/7) | 71.7%(17/11) | 84.7% |
| hizuki_a1 | Colo | 92.5%(7/0) | 82.6%(16/2) | 80.5%(9/10) | 72.1%(9/19) | 79.6% |
| houou | Colo | 92.5%(7/0) | 75.3%(25/0) | 75.2%(15/10) | 64.6%(22/14) | 86.5% |
| kairiky | Colo | 89.9%(10/0) | 60.4%(40/0) | 79.5%(13/8) | 76.4%(14/10) | 79.2% |
| kairyu | Colo | 92.7%(7/0) | 79.6%(20/0) | 77.9%(11/11) | 63.0%(13/24) | 91.6% |
| kemusso | Colo | 94.9%(5/0) | 86.9%(13/0) | 78.2%(12/10) | 74.5%(15/11) | 80.5% |
| kibanha | XD | 92.0%(8/0) | 75.3%(25/0) | 77.9%(14/8) | 75.5%(18/7) | 77.8% |
| kirlia | Colo | 93.2%(7/0) | 85.9%(14/0) | 79.5%(14/7) | 67.0%(16/17) | 84.4% |
| koduck | Colo | 94.0%(6/0) | 82.4%(18/0) | 79.4%(14/7) | 64.1%(17/19) | 82.5% |
| kyukon | Colo | 90.9%(9/0) | 71.5%(29/0) | 78.6%(13/8) | 64.2%(17/19) | 79.8% |
| lantern | Colo | 93.6%(6/0) | 81.5%(15/4) | 78.5%(13/8) | 69.2%(18/13) | 86.2% |
| laplace | Colo | 90.9%(9/0) | 62.7%(37/0) | 79.1%(11/10) | 77.4%(11/12) | 80.6% |
| lizardon | Colo | 93.5%(7/0) | 80.3%(19/0) | 76.5%(13/11) | 70.1%(14/16) | 91.6% |
| mage_0101 | XD | 91.8%(8/0) | 77.6%(21/1) | 79.6%(7/14) | 62.0%(5/33) | 56.1% |
| mcgroudon_1101 | XD | 91.6%(8/0) | 80.6%(17/2) | 78.3%(8/14) | 63.4%(7/30) | 28.0% |
| metamon | Colo | 89.0%(11/0) | 53.1%(47/0) | 80.6%(12/8) | 79.4%(11/10) | 81.0% |
| miniryu | XD | 90.2%(10/0) | 58.5%(41/0) | 80.4%(12/7) | 73.6%(12/14) | 80.7% |
| mirrabo_0101 | XD | 91.8%(8/0) | 79.7%(19/2) | 79.5%(6/14) | 61.5%(5/33) | 76.0% |
| nendoll | Colo | 93.4%(7/0) | 75.9%(21/3) | 79.9%(14/6) | 82.4%(13/4) | 90.3% |
| noctus | Colo | 93.2%(7/0) | 80.9%(19/0) | 78.0%(13/9) | 59.3%(19/22) | 79.8% |
| nukenin | XD | 97.1%(3/0) | 87.6%(12/0) | 78.7%(12/9) | 81.0%(14/5) | 94.0% |
| nyoromo | Colo | 91.4%(9/0) | 69.5%(31/0) | 78.3%(15/7) | 70.3%(19/11) | 88.1% |
| patcheel | Colo | 92.4%(8/0) | 73.7%(26/0) | 78.4%(17/5) | 66.4%(19/15) | 91.3% |
| pikachu | Colo | 93.4%(7/0) | 77.8%(22/0) | 78.4%(12/10) | 66.7%(12/21) | 88.8% |
| rayquaza | XD | 93.6%(6/0) | 84.3%(16/0) | 79.9%(17/3) | 77.6%(20/3) | 84.6% |
| rinto_0101 | XD | 93.7%(6/0) | 79.5%(14/7) | 79.9%(6/14) | 60.4%(4/35) | 44.3% |
| rinto_1101 | XD | 93.9%(6/0) | 76.3%(14/10) | 79.9%(7/13) | 63.7%(5/31) | 54.9% |
| rinto_1102 | XD | 94.3%(6/0) | 77.5%(14/9) | 79.9%(7/13) | 63.3%(5/32) | 56.8% |
| roselia | Colo | 91.0%(9/0) | 71.1%(29/0) | 79.1%(13/8) | 69.8%(17/13) | 64.9% |
| ruffresia | Colo | 90.2%(10/0) | 60.3%(40/0) | 79.6%(12/9) | 74.0%(12/14) | 83.1% |
| runpappa | XD | 92.5%(7/0) | 75.2%(25/0) | 79.1%(16/5) | 70.7%(20/9) | 81.4% |
| showers | Colo | 89.7%(10/0) | 63.4%(37/0) | 79.2%(13/7) | 70.2%(12/18) | 79.9% |
| sirnight | Colo | 92.2%(8/0) | 75.0%(25/0) | 78.6%(13/8) | 66.5%(18/16) | 81.0% |
| subame | Colo | 91.7%(8/0) | 77.4%(23/0) | 79.6%(13/7) | 72.1%(16/11) | 80.4% |
| suikun | Colo | 92.2%(8/0) | 81.2%(19/0) | 77.8%(16/6) | 63.2%(23/14) | 88.7% |
| sunnygo | Colo | 97.4%(3/0) | 89.6%(10/0) | 79.7%(13/8) | 79.3%(13/8) | 90.4% |
| thunder | Colo | 89.7%(10/0) | 61.8%(38/0) | 79.4%(11/9) | 76.8%(14/9) | 78.7% |
| tropius | Colo | 92.9%(7/0) | 81.4%(19/0) | 77.7%(15/8) | 61.1%(18/21) | 82.5% |
| usohachi | XD | 92.3%(8/0) | 71.8%(22/6) | 81.3%(10/9) | 84.7%(13/3) | 75.2% |
| vibrava | Colo | 91.6%(8/0) | 77.9%(22/0) | 79.4%(15/5) | 70.5%(19/10) | 83.6% |

**Averages (76 models):** NBN 92.3% · NIN 76.2% · BBB 78.9% · IBI 69.9% · BNB 79.0%

### Map / Scene Models

| Model | Game | NBN ✅ | NIN 🔴 | BBB 🔵 | IBI 🔵 | BNB 🟠 |
|---|---|---|---|---|---|---|
| D6_out_all | XD | 96.4%(4/0) | 18.1%(0/82) | 68.1%(13/19) | 61.2%(14/25) | 43.7% |
| M1_out | XD | 98.3%(2/0) | 23.1%(0/77) | 79.4%(8/12) | 78.0%(9/13) | 2.6% |

**Averages (2 models):** NBN 97.4% · NIN 20.6% · BBB 73.8% · IBI 69.6% · BNB 23.2%

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

**BNB** — Layout differences from DATBuilder's node ordering and alignment conventions vs the original SysDolphin compiler.
