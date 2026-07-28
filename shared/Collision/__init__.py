"""Binary structure layer for the map collision database (.ccd).

Parses and (eventually) writes the format verbatim, the way `shared/Nodes/`
does for DAT archives. Zero bpy / mathutils imports.
"""

try:
    from .structures import CCDFile, CCDEntry, CCDMesh, CCDMeshGrid, CCDPoly
    from .parser import parse_ccd
except (ImportError, SystemError):
    from shared.Collision.structures import (
        CCDFile, CCDEntry, CCDMesh, CCDMeshGrid, CCDPoly,
    )
    from shared.Collision.parser import parse_ccd
