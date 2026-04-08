"""GameCube ↔ meter scale conversion.

GameCube models use arbitrary units. A blanket scale factor converts
positions to/from real-world meters (Blender's default 1 unit = 1 meter).

The factor 0.15 was calibrated so that Pokémon official heights (from
Bulbapedia) match the model's Blender Z dimension after import.
"""

GC_TO_METERS = 0.10                # GameCube units → meters (import)
METERS_TO_GC = 1.0 / GC_TO_METERS  # meters → GameCube units (export, 10.0)
