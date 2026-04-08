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

**Overall export pipeline completion: ✅ 82%** _(weighted: NBN 25%, NIN 40%, IBI 30%, BNB 5%)_

_Average health: 🔴 0-20% · 🟠 21-40% · 🟡 41-60% · 🔵 61-80% · ✅ 81-100%_

IBI uses **category-weighted scoring**: each IR category (bones, meshes, materials, animations, constraints, lights) is scored independently, then averaged across categories that have data. Run with `python3.11` and `bpy==4.5.7`.

All scores displayed as `match%(error/miss)` — see "How Scores Are Computed" for definitions.

### Character / Pokémon Models

| Model | Game | NBN ✅ | NIN 🔵 | IBI ✅ | BNB 🔵 |
|---|---|---|---|---|---|
| nukenin | XD | 97.1%(3/0) | 87.5%(13/0) | 89.1%(8/2) | 94.0% |
| haganeil | XD | 92.7%(7/0) | 81.0%(16/4) | 84.0%(10/6) | 91.8% |
| frygon | XD | 93.0%(7/0) | 78.5%(20/2) | 83.7%(12/4) | 83.5% |
| achamo | XD | 92.0%(8/0) | 75.2%(24/1) | 84.8%(13/2) | 80.9% |
| miniryu | XD | 90.2%(10/0) | 56.9%(41/2) | 88.6%(8/4) | 80.7% |
| bohmander | XD | 91.5%(9/0) | 78.1%(21/1) | 84.8%(12/3) | 82.5% |
| cerebi | XD | 89.6%(10/0) | 61.4%(38/1) | 84.2%(10/6) | 79.0% |
| gallop | XD | 91.7%(8/0) | 77.0%(22/1) | 85.2%(10/5) | 77.3% |
| usohachi | XD | 92.3%(8/0) | 69.0%(21/10) | 86.1%(9/4) | 75.2% |
| runpappa | XD | 92.5%(7/0) | 73.9%(25/1) | 84.4%(13/2) | 81.4% |
| rayquaza | XD | 93.6%(6/0) | 82.8%(16/2) | 82.8%(16/1) | 84.6% |
| ken_a1 | XD | 91.6%(8/0) | 76.8%(21/2) | 89.8%(7/3) | 61.0% |
| mage_0101 | XD | 91.8%(8/0) | 77.8%(21/1) | 84.7%(1/14) | 56.1% |
| hinoarashi | Colo | 90.3%(10/0) | 64.4%(34/2) | 85.6%(10/4) | 84.7% |
| hizuki_a1 | Colo | 92.5%(7/0) | 82.6%(16/2) | 90.2%(6/4) | 79.6% |
| ghos | Colo | 90.3%(10/0) | 62.3%(35/3) | 83.3%(10/7) | 77.7% |
| showers | Colo | 89.7%(10/0) | 62.8%(36/1) | 88.9%(7/4) | 79.9% |

### Map / Scene Models (stretch goal)

| Model | Game | NBN | NIN | IBI | BNB |
|---|---|---|---|---|---|
| D6_out_all | XD | 96.4%(4/0) | 18.0%(0/82) | 69.7%(11/20) | 43.7% |
| M1_out | XD | 98.3%(2/0) | 22.7%(0/77) | 71.1%(8/21) | 2.6% |
| M3_out | XD | 99.2%(1/0) | 22.7%(0/77) | 72.9%(9/18) | 1.5% |

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
| Animations | ~35% | ~37% | ~28% | Errors from Euler decomposition ambiguity and slope value mismatch (finite-difference slopes vs original HSD slopes). Misses from handle_left/handle_right fields and remaining slope edge cases. Bezier sparsification now produces slope_in/slope_out via central finite differences on unbaked values |
| Constraints | ~95% | ~5% | ~0% | IK, Copy Location, Track To, Copy Rotation, Limit Rotation, Limit Location all implemented. Errors from pole angle encoding and IK bone length precision |
| Lights | ~100% | ~0% | ~0% | SUN, POINT, SPOT types round-trip correctly |

### Limiting Factors by Test Type

**IBI** — Animation accuracy (~35% match) remains the largest drag on IBI scores. Bezier sparsification with slope extraction (via central finite differences on unbaked frame values) now produces slope_in/slope_out, reducing the miss rate from ~44% to ~28%. Remaining errors come from slope value mismatch (finite-difference approximation vs original HSD tangent values) and Euler decomposition ambiguity (equivalent but numerically different rotation values). Remaining misses are handle_left/handle_right fields (not yet populated) and slope edge cases. Bone errors are inherent Blender round-trip limitations: IBM values differ from original (our IBM is self-consistent but computed differently), and accumulated parent scale drifts through Blender's edit bone normalization. Constraints and lights round-trip at ~95-100%.

**NIN** — Material color normalization is the largest NIN error source: the IR stores colors as normalized floats [0-1] while original nodes use raw u8 [0-255], causing mismatches on ambient/diffuse/specular RGBA fields across all materials. The compose phase encodes BEZIER keyframes as HSD_A_OP_SPL with slopes, sets start_frame from the first keyframe, and uses optimal quantization format selection (Colo/XD formula: `frac_bits = type_bits - ceil(log2(max_abs + 1))`). Investigation confirmed: (1) channel ordering already matches originals (ascending HSD_A_J_* constant order), (2) quantization format selection shows no systematic mismatches. Display list chunk count differences are minor (1 field per PObject). Palette data differences from C8 re-encoding. Material animations composed (color/alpha + texture UV). Structural parity is solid: DObject grouping, PObject chaining, vertex descriptors, flags, and texture format selection all match. Future optimization: encode display lists as TRI_STRIP+QUADS+TRIANGLES (originals use ~80% strips, ~12% quads, ~8% triangles).

**NBN** — Pointer resolution edge cases and alignment differences in DATBuilder. Functionally correct (field values match).

**BNB** — Layout differences from DATBuilder's node ordering and alignment conventions vs the original SysDolphin compiler.
