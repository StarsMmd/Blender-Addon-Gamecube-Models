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

Build an IRScene into Blender objects via the build phase, then read them back via the describe_blender phase to produce a new IRScene. Compare the two IR scenes using category-weighted scoring — each IR category (bones, meshes, materials, animations, constraints, lights) is scored independently, then averaged across categories that have data. This prevents large vertex arrays from inflating the score.

### Binary → Node tree → Binary (BNB)

Parse a DAT binary, write it back, and compare the output bytes against the input using a fuzzy 4-byte word matching algorithm. This measures binary-level fidelity — whether the output file would be byte-identical to the input. Exact 1:1 binary matches are a stretch goal that will require matching the original SysDolphin compiler's layout conventions (alignment, node ordering, padding). A high BNB score is purely aesthetic — it has no functional benefit. NBN determines the practical accuracy of the exporter.

---

## Test Results

**Overall export pipeline completion: 🔵 76%** _(weighted: NBN 25%, NIN 40%, IBI 30%, BNB 5%)_

_Average health: 🔴 0-20% · 🟠 21-40% · 🟡 41-60% · 🔵 61-80% · ✅ 81-100%_

IBI uses **category-weighted scoring**: each IR category (bones, meshes, materials, animations, constraints, lights) is scored independently, then averaged across categories that have data. Run with `python3.11` and `bpy==4.5.7`.

All scores displayed as `match%(error/miss)` — see "How Scores Are Computed" for definitions.

| Model | Game | NBN ✅ | NIN 🟡 | IBI ✅ | BNB 🔵 |
|---|---|---|---|---|---|
| nukenin | XD | 97.1%(3/0) | 82.2%(15/3) | 86.9%(11/2) | 94.0% |
| haganeil | XD | 92.7%(7/0) | 63.0%(30/7) | 82.3%(14/3) | 91.8% |
| cokodora | XD | 93.4%(7/0) | 65.6%(28/6) | 82.4%(15/3) | 84.3% |
| frygon | XD | 93.0%(7/0) | 65.8%(29/6) | 80.3%(15/5) | 83.5% |
| achamo | XD | 92.0%(8/0) | 59.8%(36/4) | 81.7%(16/2) | 80.9% |
| miniryu | XD | 90.2%(10/0) | 46.1%(50/4) | 86.5%(10/3) | 80.9% |
| bohmander | XD | 91.5%(9/0) | 58.7%(37/4) | 81.7%(16/3) | 80.8% |
| cerebi | XD | 89.6%(10/0) | 45.1%(52/3) | 82.5%(13/5) | 71.0% |
| gallop | XD | 91.7%(8/0) | 58.0%(36/6) | 81.9%(13/5) | 77.3% |
| usohachi | XD | 92.3%(8/0) | 52.6%(28/19) | 84.5%(12/4) | 75.1% |
| runpappa | XD | 92.5%(7/0) | 61.0%(34/5) | 80.3%(18/2) | 81.4% |
| rayquaza | XD | 93.6%(6/0) | 67.5%(24/8) | 77.4%(21/1) | 84.6% |
| ken_a1 | XD | 91.6%(8/0) | 58.5%(36/5) | 90.4%(5/5) | 61.0% |
| mage_0101 | XD | 91.8%(8/0) | 63.8%(34/2) | 82.6%(1/16) | 56.1% |
| heracros | Colo | 93.0%(7/0) | 63.6%(31/5) | 81.9%(16/2) | 77.5% |
| hinoarashi | Colo | 90.3%(10/0) | 48.7%(46/5) | 82.2%(7/11) | 83.1% |
| hizuki_a1 | Colo | 92.5%(7/0) | 64.1%(30/6) | 90.6%(6/3) | 79.6% |
| koduck | Colo | 94.0%(6/0) | 66.7%(27/6) | 78.9%(10/11) | 82.5% |
| ghos | Colo | 90.3%(10/0) | 44.1%(50/6) | 81.6%(13/6) | 77.8% |
| showers | Colo | 89.7%(10/0) | 47.5%(50/3) | 86.6%(10/4) | 76.0% |

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

# Verbose output (shows NIN and IBI mismatch details)
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
| Bones | ~82% | ~14% | ~4% | Errors: inverse_bind_matrix (different computation than original), rotation Euler ambiguity, scale inheritance position drift. Misses: hidden state (importer doesn't set edit_bone.hide) |
| Meshes | ~98% | ~0% | ~2% | Near-complete geometry round-trip. Vertex positions, bone weights, and parent_bone_index all preserved |
| Materials | ~99% | ~1% | ~0% | Specular mapped via Specular Tint correction, ambient via Emission node. GX texture format preserved via `dat_gx_format` custom property on Blender images |
| Animations | ~37% | ~53% | ~9% | Implemented — errors from keyframe sparsification and Euler decomposition ambiguity |
| Constraints | ~95% | ~5% | ~0% | IK, Copy Location, Track To, Copy Rotation, Limit Rotation, Limit Location all implemented. Errors from pole angle encoding and IK bone length precision |
| Lights | ~100% | ~0% | ~0% | SUN, POINT, SPOT types round-trip correctly |

### Limiting Factors by Test Type

**IBI** — The largest drag on IBI scores is animation accuracy (~37% match due to keyframe sparsification and Euler decomposition ambiguity). Bone errors are inherent Blender round-trip limitations: IBM values differ from original (our IBM is self-consistent but computed differently than the game tools), Euler decomposition ambiguity produces equivalent but numerically different rotation values, and accumulated parent scale drifts through Blender's edit bone normalization. Constraints and lights now round-trip at ~95-100%.

**NIN** — Display list chunk count differences (we use GX_DRAW_TRIANGLES without triangle strip optimization, producing ~1.5-2x larger display lists) and palette data differences (C8 re-encoding produces different color quantization). Structural parity is solid: DObject grouping, PObject chaining, vertex descriptors, flags, and texture format selection all match the original.

**NBN** — Pointer resolution edge cases and alignment differences in DATBuilder. Functionally correct (field values match).

**BNB** — Layout differences from DATBuilder's node ordering and alignment conventions vs the original SysDolphin compiler.
