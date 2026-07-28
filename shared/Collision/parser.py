"""Binary .ccd reader: bytes → CCDFile.

All pointers in the file are byte offsets from file start (0 = null) and all
values are big-endian. Pure parsing — no bpy, no interpretation of the poly
metadata halfwords.
"""

try:
    from ..helpers.binary import read, read_many
    from ..helpers.logger import StubLogger
    from ..Constants.collision import (
        CollisionSubsystem, SUBSYSTEM_ORDER, GRIDDED_SUBSYSTEMS,
        CCD_FILE_HEAD_SIZE, CCD_ENTRY_SIZE, CCD_CELL_SIZE,
        CCD_POLY_SIZE, CCD_SUN_POLY_SIZE,
    )
    from .structures import CCDFile, CCDEntry, CCDMesh, CCDMeshGrid, CCDPoly
except (ImportError, SystemError):
    from shared.helpers.binary import read, read_many
    from shared.helpers.logger import StubLogger
    from shared.Constants.collision import (
        CollisionSubsystem, SUBSYSTEM_ORDER, GRIDDED_SUBSYSTEMS,
        CCD_FILE_HEAD_SIZE, CCD_ENTRY_SIZE, CCD_CELL_SIZE,
        CCD_POLY_SIZE, CCD_SUN_POLY_SIZE,
    )
    from shared.Collision.structures import (
        CCDFile, CCDEntry, CCDMesh, CCDMeshGrid, CCDPoly,
    )

# Entry field offsets.
_ENTRY_POSITION = 0x00
_ENTRY_ROTATION = 0x0C
_ENTRY_SCALE = 0x18
_ENTRY_MESH_POINTERS = 0x24    # six u32, one per subsystem in SUBSYSTEM_ORDER
_ENTRY_FLAGS = 0x3C

# Mesh head field offsets (the first two are common to both head shapes).
_HEAD_POLY_POINTER = 0x00
_HEAD_POLY_COUNT = 0x04
_HEAD_CELL_POINTER = 0x08
_HEAD_INDEX_POOL_POINTER = 0x0C
_HEAD_GRID_WIDTH = 0x10
_HEAD_GRID_HEIGHT = 0x12
_HEAD_CELL_SIZE_X = 0x14
_HEAD_CELL_SIZE_Z = 0x18
_HEAD_ORIGIN_X = 0x1C
_HEAD_ORIGIN_Z = 0x20

# Poly field offsets.
_POLY_NORMAL = 0x24
_POLY_META0 = 0x30
_POLY_META1 = 0x32


def parse_ccd(data, name="", logger=StubLogger()):
    """Parse a collision database into its binary structure representation.

    In: data (bytes, complete .ccd file); name (str, base name kept on the
        result for naming and logging); logger (Logger, defaults to StubLogger).
    Out: CCDFile. Raises ValueError when the header or any pointer would read
        outside the file.
    """
    if len(data) < CCD_FILE_HEAD_SIZE:
        raise ValueError(
            "%s is %d bytes — too short to hold a CCD file header"
            % (name or "CCD", len(data))
        )

    entries_offset = read('uint', data, 0x00)
    entry_count = read('uint', data, 0x04)
    _require_span(data, entries_offset, entry_count * CCD_ENTRY_SIZE,
                  name, "entry table")
    if entries_offset < CCD_FILE_HEAD_SIZE:
        raise ValueError(
            "%s: entry table offset 0x%X overlaps the file header"
            % (name or "CCD", entries_offset)
        )

    entries = []
    for index in range(entry_count):
        base = entries_offset + index * CCD_ENTRY_SIZE
        entry = CCDEntry(
            index=index,
            position=tuple(read_many('float', 3, data, base + _ENTRY_POSITION)),
            rotation=tuple(read_many('float', 3, data, base + _ENTRY_ROTATION)),
            scale=tuple(read_many('float', 3, data, base + _ENTRY_SCALE)),
            flags=read('ushort', data, base + _ENTRY_FLAGS),
        )
        for slot, subsystem in enumerate(SUBSYSTEM_ORDER):
            head = read('uint', data, base + _ENTRY_MESH_POINTERS + slot * 4)
            if head:
                entry.meshes[subsystem] = _parse_mesh(data, head, subsystem, name)
        entries.append(entry)

    total_polys = sum(len(mesh.polys)
                      for entry in entries for mesh in entry.meshes.values())
    logger.info("  Parsed CCD %s: %d entr%s, %d poly(s)",
                name or "(unnamed)", len(entries),
                "y" if len(entries) == 1 else "ies", total_polys)
    return CCDFile(name=name, entries=entries)


def _parse_mesh(data, head, subsystem, name):
    """Parse one subsystem mesh from its head offset."""
    poly_offset = read('uint', data, head + _HEAD_POLY_POINTER)
    poly_count = read('uint', data, head + _HEAD_POLY_COUNT)
    poly_size = (CCD_SUN_POLY_SIZE if subsystem is CollisionSubsystem.SUN
                 else CCD_POLY_SIZE)
    _require_span(data, poly_offset, poly_count * poly_size,
                  name, "%s polys" % subsystem.value)

    polys = [_parse_poly(data, poly_offset + i * poly_size, poly_size)
             for i in range(poly_count)]

    grid = None
    if subsystem in GRIDDED_SUBSYSTEMS:
        grid = _parse_grid(data, head, poly_count, subsystem, name)

    return CCDMesh(subsystem=subsystem, polys=polys, grid=grid)


def _parse_poly(data, offset, poly_size):
    """Parse one triangle. Sun polys stop before the metadata halfwords."""
    poly = CCDPoly(
        v0=tuple(read_many('float', 3, data, offset + 0x00)),
        v1=tuple(read_many('float', 3, data, offset + 0x0C)),
        v2=tuple(read_many('float', 3, data, offset + 0x18)),
        normal=tuple(read_many('float', 3, data, offset + _POLY_NORMAL)),
    )
    if poly_size > CCD_SUN_POLY_SIZE:
        poly.meta0 = read('ushort', data, offset + _POLY_META0)
        poly.meta1 = read('ushort', data, offset + _POLY_META1)
    return poly


def _parse_grid(data, head, poly_count, subsystem, name):
    """Parse the XZ lookup grid of a gridded mesh."""
    cell_offset = read('uint', data, head + _HEAD_CELL_POINTER)
    pool_offset = read('uint', data, head + _HEAD_INDEX_POOL_POINTER)
    width = read('ushort', data, head + _HEAD_GRID_WIDTH)
    height = read('ushort', data, head + _HEAD_GRID_HEIGHT)
    _require_span(data, cell_offset, width * height * CCD_CELL_SIZE,
                  name, "%s grid cells" % subsystem.value)

    cells = []
    pool_length = 0
    for i in range(width * height):
        base = cell_offset + i * CCD_CELL_SIZE
        pool_index = read('uint', data, base)
        count = read('uint', data, base + 4)
        cells.append((pool_index, count))
        pool_length = max(pool_length, pool_index + count)

    _require_span(data, pool_offset, pool_length * 4,
                  name, "%s grid index pool" % subsystem.value)
    index_pool = list(read_many('uint', pool_length, data, pool_offset)) if pool_length else []

    out_of_range = [i for i in index_pool if i >= poly_count]
    if out_of_range:
        raise ValueError(
            "%s: %s grid index pool references poly %d but the mesh has only "
            "%d" % (name or "CCD", subsystem.value, out_of_range[0], poly_count)
        )

    return CCDMeshGrid(
        width=width, height=height,
        cell_size_x=read('float', data, head + _HEAD_CELL_SIZE_X),
        cell_size_z=read('float', data, head + _HEAD_CELL_SIZE_Z),
        origin_x=read('float', data, head + _HEAD_ORIGIN_X),
        origin_z=read('float', data, head + _HEAD_ORIGIN_Z),
        cells=cells,
        index_pool=index_pool,
    )


def _require_span(data, offset, length, name, what):
    """Raise unless [offset, offset + length) lies inside the file."""
    if offset < 0 or length < 0 or offset + length > len(data):
        raise ValueError(
            "%s: %s at 0x%X spans %d bytes, past the end of the %d-byte file"
            % (name or "CCD", what, offset, length, len(data))
        )
