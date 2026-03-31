# Complexity Optimization Plan

Algorithmic complexity hotspots across both pipelines, identified via audit. Items 4-8 are minor and can be done opportunistically.

---

## Completed Optimizations (2026-03-31)

| Fix | File | Change |
|-----|------|--------|
| `Node.toList()` O(n²) → O(n) | `shared/Nodes/Node.py` | Set-based address dedup |
| `VertexList` dedup O(V·N·V) → O(N) | `shared/Nodes/Classes/Mesh/VertexList.py` | Pre-built max buffer map + bulk write |
| `_evaluate_track()` O(n) → O(log n) | `importer/phases/describe/helpers/material_animations.py` | Binary search |
| `_get_parent()` O(n) → O(1) | `importer/phases/describe/helpers/constraints.py` | Reverse index map |
| `NodeTypes` functions recomputation | `shared/Nodes/NodeTypes.py` | `@lru_cache` on `get_type_length`, `get_alignment_at_offset`, `markUpFieldType` |
| `_bake_bone_track()` per-frame insert | `importer/phases/build_blender/helpers/animations.py` | Batch `add()` + bulk `.co` set instead of per-frame `insert()` |
| `parseNode()` bound injection O(f²) → O(f) | `importer/phases/parse/helpers/dat_parser.py` | Dict-based single pass over fields |
| `PObject.read_geometry()` `.keys()` → direct dict | `shared/Nodes/Classes/Mesh/PObject.py` | `index not in norm_dict` instead of `index in norm_dict.keys()` |

---

## Remaining Opportunities

### 4. Static pose detection — LOW
**File:** `importer/phases/build_blender/helpers/animations.py:116-126`

Scans all fcurves × keypoints post-bake. Could track during bake instead.

### 5. Envelope normal transforms — LOW
**File:** `importer/phases/describe/helpers/meshes.py:449-465`

Per-vertex matrix multiply is inherently O(loops). Numpy vectorization possible but limited gains.

### 6. `Node.allocationSize()` — LOW
**File:** `shared/Nodes/Node.py:143-148`

Called per instance. Could cache per node class since allocation size is class-level.

### 7. VertexList `type().__name__` check — LOW
**File:** `shared/Nodes/Classes/Mesh/VertexList.py:34-47`

String comparison instead of `isinstance()`.

### 8. `DATBuilder.writeNode()` double pass — LOW
**File:** `exporter/phases/serialize/helpers/dat_builder.py:267-378`

Two passes over fields (resolve addresses, then write). Could combine into one pass.
