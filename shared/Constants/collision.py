"""Constants for the map collision database (.ccd).

Layout sizes, metadata masks and grid-derivation rules, plus the subsystem
enum shared by the binary structure layer, the IR and the BR. Neither side
depends on the other — they meet here.

Format reference: technical-docs/collision_format.md.
"""
from enum import Enum


class CollisionSubsystem(Enum):
    """The six collision meshes an entry can carry, in file slot order.

    Named for what each one does rather than for the engine's own terms; the
    format doc maps them to the runtime's `walk / hit / thru / check / hit_npc
    / sun` slots and to the `GScolsys2` functions that read them.
    """
    WALK = "WALK"                        # ground polys: height + layer lookup
    WALL = "WALL"                        # wall polys that block the player
    ZONE_TRIGGER = "ZONE_TRIGGER"        # walk-through trigger polys
    BUTTON_TRIGGER = "BUTTON_TRIGGER"    # A-button / inspection trigger polys
    NPC_WALL = "NPC_WALL"                # wall polys that block NPCs
    SUN = "SUN"                          # lens-flare occluders


# The order the six mesh pointers appear in an entry, and the order mesh
# sections are grouped on disk.
SUBSYSTEM_ORDER = (
    CollisionSubsystem.WALK,
    CollisionSubsystem.WALL,
    CollisionSubsystem.ZONE_TRIGGER,
    CollisionSubsystem.BUTTON_TRIGGER,
    CollisionSubsystem.NPC_WALL,
    CollisionSubsystem.SUN,
)

# Human-readable labels for the UI.
SUBSYSTEM_LABELS = {
    CollisionSubsystem.WALK: "Walk",
    CollisionSubsystem.WALL: "Wall",
    CollisionSubsystem.ZONE_TRIGGER: "Zone Trigger",
    CollisionSubsystem.BUTTON_TRIGGER: "Button Trigger",
    CollisionSubsystem.NPC_WALL: "NPC Wall",
    CollisionSubsystem.SUN: "Sun",
}

# Subsystems whose polys carry an event/region ID — the number the map's
# scripts key off. Everything else has no region concept at all.
REGION_SUBSYSTEMS = frozenset({
    CollisionSubsystem.ZONE_TRIGGER,
    CollisionSubsystem.BUTTON_TRIGGER,
})

# Subsystems whose mesh head carries an XZ lookup grid. The other two use the
# short head — just a poly pointer and a count.
GRIDDED_SUBSYSTEMS = frozenset({
    CollisionSubsystem.WALK,
    CollisionSubsystem.WALL,
    CollisionSubsystem.ZONE_TRIGGER,
    CollisionSubsystem.NPC_WALL,
})

CCD_FILE_HEAD_SIZE = 0x08
CCD_ENTRY_SIZE = 0x40
CCD_GRID_MESH_HEAD_SIZE = 0x24
CCD_SIMPLE_MESH_HEAD_SIZE = 0x08
CCD_CELL_SIZE = 0x08
CCD_POLY_SIZE = 0x34
CCD_SUN_POLY_SIZE = 0x30      # sun polys carry no metadata halfwords

# Entry flag bit 0: the entry's transform is re-applied per frame.
CCD_ENTRY_FLAG_DYNAMIC = 0x0001

# Grid derivation: square cells of this extent, unless an axis would then need
# more than the cap, in which case that axis is divided into exactly MAX cells.
CCD_GRID_CELL_EXTENT = 40.0
CCD_MAX_GRID_CELLS = 32

# Walk layer nibble meaning "matches whichever layer the actor is on".
WALK_LAYER_ANY = 0xF

# Edge-enable mask: bit 0 = edge v0→v1, bit 1 = v1→v2, bit 2 = v2→v0.
EDGE_MASK_ALL = 0b111
