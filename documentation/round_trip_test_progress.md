# Round-Trip Test Progress

Each round-trip test works by taking the result of an import step, running the equivalent export step on it, and checking how close the output is to what we started with. This is the most direct way to verify that each exporter step works as intended.

This document tracks the fidelity of the export pipeline by measuring how accurately data survives each round-trip path. When NBN, NIN, and IBI all approach 100%, the exporter is functionally complete.

---

## Round-Trip Types

### Node tree → Binary → Node tree (NBN)

Parse a DAT binary into a node tree, serialize it back via DATBuilder, reparse the output, and compare node fields. Measures whether the DATBuilder preserves all node data through the binary format. Mismatches typically come from pointer resolution edge cases or alignment differences.

### Node tree → IR → Node tree (NIN)

Parse a DAT binary into a node tree, run the describe phase to produce an IRScene, then run the compose phase to reconstruct a node tree. Compare the composed node tree against the original. Measures how much data survives the IR round-trip. The NIN score reflects the **full** node tree (not just the fields we've implemented compose for), so it naturally increases as more compose helpers are added.

### IR → Blender → IR (IBI)

Build an IRScene into Blender objects via the build phase, then read them back via the describe_blender phase to produce a new IRScene. Compare the two IR scenes using category-weighted scoring — each IR category (bones, meshes, materials, animations, constraints, lights) is scored independently, then averaged across categories that have data. This prevents large vertex arrays from inflating the score. Currently covers bones and mesh geometry; materials, animations, and constraints are not yet implemented in the export describe phase.

### Binary → Node tree → Binary (BNB)

Parse a DAT binary, write it back, and compare the output bytes against the input using a fuzzy 4-byte word matching algorithm. This measures binary-level fidelity — whether the output file would be byte-identical to the input. Exact 1:1 binary matches are a stretch goal that will require matching the original SysDolphin compiler's layout conventions (alignment, node ordering, padding). Current scores are 70–95% due to layout differences. A high BNB score is purely aesthetic — it has no functional benefit. NBN determines the practical accuracy of the exporter.

---

## Test Results

**Overall export pipeline completion: 🔵 62.3%** _(weighted: NBN 25%, NIN 40%, IBI 30%, BNB 5%)_

_Average health: 🔴 0-20% · 🟠 21-40% · 🟡 41-60% · 🔵 61-80% · ✅ 81-100%_

IBI uses **category-weighted scoring**: each IR category (bones, meshes, materials, animations, constraints, lights) is scored independently, then averaged across categories that have data. This prevents large vertex arrays from inflating the score. Run with `python3.11` and `bpy==4.5.7`.

All scores displayed as `match%(error/miss)` — see "How Scores Are Computed" for definitions.

| Model | Game | NBN ✅ | NIN 🟡 | IBI 🟡 | BNB 🔵 |
|---|---|---|---|---|---|
| nukenin | XD | 95.8%(4/0) | 73.2%(23/4) | 52.8%(1/46) | 94.0% |
| haganeil | XD | 92.4%(8/0) | 58.1%(35/7) | 54.7%(2/43) | 91.8% |
| cokodora | XD | 93.0%(7/0) | 55.0%(35/10) | 50.4%(2/48) | 84.3% |
| frygon | XD | 92.9%(7/0) | 58.9%(35/6) | 48.7%(1/50) | 83.5% |
| achamo | XD | 91.9%(8/0) | 54.2%(41/4) | 49.9%(2/49) | 80.9% |
| miniryu | XD | 90.0%(10/0) | 44.2%(52/4) | 49.3%(1/50) | 80.9% |
| bohmander | XD | 91.4%(9/0) | 53.4%(42/5) | 50.1%(1/49) | 80.8% |
| cerebi | XD | 89.5%(10/0) | 44.4%(53/3) | 47.9%(2/50) | 71.0% |
| gallop | XD | 91.6%(8/0) | 51.7%(42/6) | 49.3%(1/49) | 77.3% |
| usohachi | XD | 92.1%(8/0) | 46.4%(35/19) | 42.0%(3/55) | 75.1% |
| runpappa | XD | 92.4%(8/0) | 55.5%(40/5) | 50.0%(2/48) | 81.4% |
| rayquaza | XD | 93.1%(7/0) | 57.1%(32/10) | 47.1%(3/50) | 84.6% |
| ken_a1 | XD | 91.5%(9/0) | 49.7%(44/6) | 40.1%(1/59) | 61.0% |
| mage_0101 | XD | 91.6%(8/0) | 51.1%(44/5) | 40.2%(1/59) | 56.1% |
| heracros | Colo | 92.8%(7/0) | 57.3%(37/5) | 50.8%(4/46) | 77.5% |
| hinoarashi | Colo | 90.2%(10/0) | 46.4%(48/5) | 47.8%(2/50) | 83.1% |
| hizuki_a1 | Colo | 92.4%(8/0) | 53.7%(39/7) | 39.2%(2/59) | 79.6% |
| koduck | Colo | 93.8%(6/0) | 56.1%(36/8) | 50.6%(3/47) | 82.5% |
| ghos | Colo | 90.2%(10/0) | 41.3%(53/6) | 46.8%(2/51) | 77.8% |
| showers | Colo | 89.6%(10/0) | 45.6%(51/3) | 49.4%(1/50) | 76.0% |

---

## How Scores Are Computed

All scores are displayed as **`match%(error/miss)`** where:
- **match** — percentage of fields that round-tripped correctly
- **error** — percentage of fields that existed in both but had different values (implementation bugs)
- **miss** — percentage of fields that existed in the original but were missing/None in the round-tripped result (not yet implemented)

Scoring methods:
- **BNB**: Fuzzy 4-byte word matching — splits both binaries into words, counts matches by value (not position). All non-matches are errors (layout differences).
- **NBN**: Recursively compares all node fields after serialize → reparse. Distinguishes errors (value mismatch) from misses (missing node/field).
- **NIN**: Walks the full original node tree as the denominator. Missing subtrees in the composed output count as misses; differing values count as errors.
- **IBI**: Category-weighted scoring. Each IR category (bones, meshes, materials, animations, constraints, lights) is scored independently, then averaged across categories that have data. Empty categories are excluded.

---

## How to Run Round-Trip Tests

All four test types (NBN, NIN, IBI, BNB) are run via a single script that operates on real model files. Requires Python 3.11 with `bpy==4.5.7` (see README for install instructions).

```bash
# Single model
python3.11 tests/round_trip/run_round_trips.py ~/Documents/Projects/DAT\ plugin/models/nukenin.pkx

# Multiple models
python3.11 tests/round_trip/run_round_trips.py model1.pkx model2.pkx

# All models in a directory
python3.11 tests/round_trip/run_round_trips.py ~/Documents/Projects/DAT\ plugin/models/

# Verbose output (shows IBI mismatch details)
python3.11 tests/round_trip/run_round_trips.py ~/Documents/Projects/DAT\ plugin/models/nukenin.pkx -v
```

Synthetic round-trip tests (no game files needed) also run as part of the main pytest suite:

```bash
python3 -m pytest tests/test_write_roundtrip.py -v
```

---

## IBI Category Breakdown

Average per-category scores across all 20 test models:

| Category | Score | Error | Miss | Notes |
|---|---|---|---|---|
| Bones | ~57% | ~5% | ~38% | Errors: flag mismatches, rotation ambiguity. Misses: inverse_bind_matrix, SKELETON flag on deformation bones |
| Meshes | ~93% | ~0% | ~7% | Near-complete geometry round-trip. Misses: parent_bone_index differences |
| Materials | ~99% | ~1% | ~0% | Specular mapped via Specular Tint correction, ambient via Emission node. Convenience fields (image_id, palette_id) excluded from scoring. |
| Animations | ~0% | ~0% | ~100% | Placeholder rest-pose stubs only. Real animation export not yet implemented |
| Constraints | 0% | 0% | 100% | Not yet implemented in export describe phase |
| Lights | — | — | — | Not yet implemented; excluded from scoring when absent |
