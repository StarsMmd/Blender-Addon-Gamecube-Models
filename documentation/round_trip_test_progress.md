# Round-Trip Test Progress

This document tracks the fidelity of the export pipeline by measuring how accurately data survives each round-trip path. When NBN, NIN, and IBI all approach 100%, the exporter is functionally complete.

---

## Round-Trip Types

### Node tree → Binary → Node tree (NBN)

Parse a DAT binary into a node tree, serialize it back via DATBuilder, reparse the output, and compare node fields. Measures whether the DATBuilder preserves all node data through the binary format. Mismatches typically come from pointer resolution edge cases or alignment differences.

### Node tree → IR → Node tree (NIN)

Parse a DAT binary into a node tree, run the describe phase to produce an IRScene, then run the compose phase to reconstruct a node tree. Compare the composed node tree against the original. Measures how much data survives the IR round-trip. The NIN score reflects the **full** node tree (not just the fields we've implemented compose for), so it naturally increases as more compose helpers are added.

### IR → Blender → IR (IBI)

Build an IRScene into Blender objects via the build phase, then read them back via the describe_blender phase to produce a new IRScene. Compare the two IR scenes field-by-field. Measures the Blender round-trip fidelity. Currently 0% as describe_blender is not yet implemented.

### Binary → Node tree → Binary (BNB)

Parse a DAT binary, write it back, and compare the output bytes against the input using a fuzzy 4-byte word matching algorithm. This measures binary-level fidelity — whether the output file would be byte-identical to the input. Exact 1:1 binary matches are a stretch goal that will require matching the original SysDolphin compiler's layout conventions (alignment, node ordering, padding). Current scores are 70–95% due to layout differences. A high BNB score is purely aesthetic — it has no functional benefit. NBN determines the practical accuracy of the exporter.

---

## Test Results

| Model | Game | NBN | NIN | IBI | BNB |
|---|---|---|---|---|---|
| nukenin | XD | 93.7% | 47.3% | — | 94.0% |
| haganeil | XD | 91.8% | 51.4% | — | 91.8% |
| cokodora | XD | 92.2% | 48.0% | — | 84.3% |
| frygon | XD | 92.4% | 63.1% | — | 83.5% |
| achamo | XD | 91.3% | 67.8% | — | 80.9% |
| miniryu | XD | 89.4% | 53.1% | — | 80.9% |
| bohmander | XD | 90.9% | 62.1% | — | 80.8% |
| cerebi | XD | 89.0% | 69.4% | — | 71.0% |
| gallop | XD | 91.1% | 69.6% | — | 77.3% |
| usohachi | XD | 91.7% | 51.2% | — | 75.1% |
| runpappa | XD | 91.8% | 61.0% | — | 81.4% |
| heracros | Colo | 92.4% | 64.8% | — | 77.5% |
| hinoarashi | Colo | 89.8% | 54.8% | — | 83.1% |
| hizuki_a1 | Colo | 91.7% | 72.3% | — | 79.6% |
| koduck | Colo | 93.2% | 67.8% | — | 82.5% |
| ghos | Colo | 89.8% | 54.7% | — | 77.8% |
| ken_a1 | XD | — | — | — | — |
| mage_0101 | XD | — | — | — | — |
| rayquaza | XD | — | — | — | — |
| showers | Colo | — | — | — | — |

_"—" = not yet measured. IBI is 0% for all models (describe_blender not implemented). NIN scores reflect skeleton-only compose — they will increase as meshes, materials, and animations are added._

---

## How Scores Are Computed

- **BNB**: `compute_binary_match()` in `tests/test_write_roundtrip.py` — splits both binaries into 4-byte words, counts matching words by value (not position) using Counter intersection, divides by the larger word count.
- **NBN**: `compare_nodes()` in `test_dat_write.py` — recursively compares all node fields, counts mismatches vs total fields.
- **NIN**: Same as NBN but compares the original parsed node tree against the composed node tree (after describe → compose). Uses the full original node tree field count as the denominator.
- **IBI**: Not yet implemented.

---

## How to Run Each Test Variant

### Node tree → Binary → Node tree and Binary → Node tree → Binary (NBN + BNB, automated)

The synthetic round-trip tests run as part of the normal test suite:

```bash
python3 -m pytest tests/test_write_roundtrip.py -v
```

### Node tree → Binary → Node tree and Binary → Node tree → Binary (NBN + BNB, real model files)

Pass a real `.dat` or `.pkx` file via the `--dat-file` flag. These tests are skipped when no file is provided:

```bash
python3 -m pytest tests/test_write_roundtrip.py --dat-file ~/Documents/Projects/DAT\ plugin/models/nukenin.pkx -v
```

### Node tree → IR → Node tree (NIN)

NIN tests compare the original parsed node tree against the output of describe → compose. Currently there is no standalone NIN test command — scores are computed by the score generation utility (see below).

### IR → Blender → IR (IBI)

IBI tests compare an IRScene against the result of build → describe_blender. Currently returns 0% as describe_blender is not yet implemented.

### Regenerating the Score Table

Scores can be regenerated using `utilities/run_round_trip_scores.py` (to be created) or computed manually using `test_dat_write.py`:

```bash
python3 test_dat_write.py ~/Documents/Projects/DAT\ plugin/models/nukenin.pkx
```
