from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .skeleton import IRModel
    from .lights import IRLight
    from .camera import IRCamera
    from .fog import IRFog


@dataclass
class IRScene:
    """Root of the Intermediate Representation. One per import operation."""
    models: list[IRModel] = field(default_factory=list)
    lights: list[IRLight] = field(default_factory=list)
    cameras: list[IRCamera] = field(default_factory=list)
    fogs: list[IRFog] = field(default_factory=list)
