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

**Overall export pipeline completion: 🔵 61.5%** _(weighted: NBN 25%, NIN 40%, IBI 30%, BNB 5%)_

_Average health: 🔴 0-20% · 🟠 21-40% · 🟡 41-60% · 🔵 61-80% · ✅ 81-100%_

IBI uses **category-weighted scoring**: each IR category (bones, meshes, materials, animations, constraints, lights) is scored independently, then averaged across categories that have data. This prevents large vertex arrays from inflating the score. Run with `python3.11` and `bpy==4.5.7`.

| Model | Game | NBN ✅ | NIN 🟡 | IBI 🟡 | BNB 🔵 |
|---|---|---|---|---|---|
| nukenin | XD | 95.8% | 72.9% | 49.9% | 94.0% |
| haganeil | XD | 92.4% | 58.1% | 52.2% | 91.8% |
| cokodora | XD | 93.0% | 55.0% | 47.4% | 84.3% |
| frygon | XD | 92.9% | 58.9% | 46.0% | 83.5% |
| achamo | XD | 91.9% | 54.2% | 47.1% | 80.9% |
| miniryu | XD | 90.0% | 44.2% | 46.5% | 80.9% |
| bohmander | XD | 91.4% | 53.4% | 47.1% | 80.8% |
| cerebi | XD | 89.5% | 44.4% | 44.8% | 71.0% |
| gallop | XD | 91.6% | 51.7% | 46.6% | 77.3% |
| usohachi | XD | 92.1% | 46.3% | 39.7% | 75.1% |
| runpappa | XD | 92.4% | 55.4% | 47.2% | 81.4% |
| rayquaza | XD | 93.1% | 56.9% | 45.0% | 84.6% |
| ken_a1 | XD | 91.5% | 49.7% | 37.9% | 61.0% |
| mage_0101 | XD | 91.6% | 51.0% | 38.1% | 56.1% |
| heracros | Colo | 92.8% | 57.3% | 48.2% | 77.5% |
| hinoarashi | Colo | 90.2% | 46.4% | 44.9% | 83.1% |
| hizuki_a1 | Colo | 92.4% | 53.7% | 37.3% | 79.6% |
| koduck | Colo | 93.8% | 56.1% | 47.3% | 82.5% |
| ghos | Colo | 90.2% | 41.3% | 44.1% | 77.8% |
| showers | Colo | 89.6% | 45.6% | 46.4% | 76.0% |

---

## How Scores Are Computed

- **BNB**: `compute_binary_match()` in `tests/test_write_roundtrip.py` — splits both binaries into 4-byte words, counts matching words by value (not position) using Counter intersection, divides by the larger word count.
- **NBN**: Recursively compares all node fields after serialize → reparse. Counts mismatches vs total fields.
- **NIN**: Walks the full original node tree as the denominator, compares against the composed node tree (after describe → compose).
- **IBI**: Category-weighted scoring. Each IR category (bones, meshes, materials, animations, constraints, lights) is scored independently using a generic dataclass walker, then averaged across categories that have data in the original IR. Empty categories are excluded from the average.

---

## How to Run Round-Trip Tests

All four test types (NBN, NIN, IBI, BNB) are run via a single script that operates on real model files. Requires `bpy` and `mathutils` as standalone Python modules (`pip install bpy mathutils`).

```bash
# Single model
python3 tests/round_trip/run_round_trips.py ~/Documents/Projects/DAT\ plugin/models/nukenin.pkx

# All models in a directory
python3 tests/round_trip/run_round_trips.py ~/Documents/Projects/DAT\ plugin/models/

# Verbose output (shows IBI mismatch details)
python3 tests/round_trip/run_round_trips.py ~/Documents/Projects/DAT\ plugin/models/nukenin.pkx -v
```

Synthetic round-trip tests (no game files needed) also run as part of the main pytest suite:

```bash
python3 -m pytest tests/test_write_roundtrip.py -v
```
