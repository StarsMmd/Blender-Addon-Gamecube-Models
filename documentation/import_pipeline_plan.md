# Import Pipeline — Implementation Status

## Overview

The import pipeline is fully implemented as 5 distinct phases. Each phase is a pure function with defined inputs/outputs and no shared mutable state.

```
Phase 1 (extract)        → raw file bytes → list[(DAT bytes, metadata)]
Phase 2 (route)          → DAT bytes → {section_name: node_type_name}
Phase 3 (parse)          → DAT bytes + section_map → list[SectionInfo]
Phase 4 (describe)       → sections → IRScene
Phase 5A (build_blender) → IRScene → Blender scene objects
```

## Phase Status

| Phase | Location | Status |
|-------|----------|--------|
| 1 — Container Extraction | `importer/phases/extract/extract.py` | ✅ Complete (.dat, .pkx) |
| 2 — Section Routing | `importer/phases/route/route.py` | ✅ Complete |
| 3 — Node Tree Parsing | `importer/phases/parse/parse.py` | ✅ Complete |
| 4 — Scene Description | `importer/phases/describe/describe.py` | ✅ Complete |
| 5A — Blender Build | `importer/phases/build_blender/build_blender.py` | ✅ Complete |
| 5B — Blend Export (future) | Not started | Planned |

## Feature Status

| Feature | Describe | Build | Notes |
|---------|----------|-------|-------|
| Bones (Joint tree → flat IRBone) | ✅ | ✅ | Scale correction pre-computed |
| Meshes (PObject → IRMesh) | ✅ | ✅ | Envelope deformation in describe |
| Materials (MaterialObject → IRMaterial) | ✅ | ✅ | Full shader node tree |
| Textures + Images | ✅ | ✅ | Decoded during parse, bytes in IR |
| Bone Animations | ✅ | ✅ | Generic keyframes in IR, Blender baking in build |
| Material Animations (color/alpha/UV) | ✅ | ✅ | sRGB conversion in describe |
| Constraints (IK, copy loc/rot, track-to, limits) | ✅ | ✅ | |
| Lights (SUN, POINT, SPOT) | ✅ | ✅ | |
| Bone Instances (JOBJ_INSTANCE) | ✅ | ✅ | |
| Shape Animation | ❌ | ❌ | Legacy stub only |
| Camera | ❌ | ❌ | Legacy stub only |
| Fog | ❌ | ❌ | Legacy stub only |

## Cleanup Status

- [x] shared/Nodes/ stripped of all bpy/build code (2,490 lines removed)
- [x] shared/Errors/ removed (replaced with ValueError)
- [x] shared/IO/ModelBuilder.py removed
- [x] Logger/file_io moved to shared/helpers/
- [x] DATParser moved to parse phase helpers
- [x] Keyframe decoder moved to describe phase helpers
- [x] No cross-phase imports
- [x] No circular dependencies
- [ ] Legacy path still available via toggle (intentional)
- [ ] Delete legacy/ directory (when ready)
