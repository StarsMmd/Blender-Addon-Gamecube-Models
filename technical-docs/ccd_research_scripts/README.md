# CCD research scripts

Standalone verification harnesses from the collision-format reverse-engineering
work (2026-07-21). No plugin imports — plain `python3`. They read the dumped
corpus directly:

- `~/Documents/GoD Tool/XD GoD Tool dumped/Game Files/` (XD, full)
- `~/Documents/GoD Tool/Colo CM Tool/Game Files/` (Colosseum, partial)

Findings are written up in [`../collision_format.md`](../collision_format.md).
These scripts are the evidence behind that doc — re-run them after any exporter
change to confirm the format assumptions still hold on real files.

| Script | What it proves |
|---|---|
| `deep_analysis.py` | Byte-coverage (0 unexplained bytes / 185 files), grid derivability (origin = AABB min, 40×40 cells, 32 cap), deterministic disk order, per-subsystem metadata stats, entry-composition histogram. |
| `interaction_xcheck.py` | CCD ↔ common.rel linkage: every InteractionPoint region index is a CCD event ID (152/152 XD rooms); every Doors-table entry index is a valid hit-only entry (154/154 XD doors). Imports `deep_analysis.analyze`. |

`parse_ccd.py` and `scan_headers.py` (early header/layout validators) were not
re-materialized — their logic is fully subsumed by `deep_analysis.analyze()`.
The paths at the top of each file are absolute; update them if the corpus moves.
