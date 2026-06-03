from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class BRConstraints:
    """Pass-through wrapper around an IRModel's constraint lists.

    The IR constraint dataclasses already mirror Blender's constraint API
    (target_bone, track_axis, owner_space, etc.) so there's nothing to
    reinterpret. This wrapper exists to satisfy the architectural boundary
    — ``build_blender`` should see BR types only — without churning
    legitimately 1:1 mappings.

    Each field holds the corresponding IR constraint list by reference.
    """
    ik: list = field(default_factory=list)              # list[IRIKConstraint]
    copy_location: list = field(default_factory=list)   # list[IRCopyLocationConstraint]
    track_to: list = field(default_factory=list)        # list[IRTrackToConstraint]
    copy_rotation: list = field(default_factory=list)   # list[IRCopyRotationConstraint]
    limit_rotation: list = field(default_factory=list)  # list[IRLimitRotationConstraint]
    limit_location: list = field(default_factory=list)  # list[IRLimitLocationConstraint]

    @property
    def is_empty(self):
        return not (self.ik or self.copy_location or self.track_to
                    or self.copy_rotation or self.limit_rotation
                    or self.limit_location)

    @property
    def total(self):
        return (len(self.ik) + len(self.copy_location) + len(self.track_to)
                + len(self.copy_rotation) + len(self.limit_rotation)
                + len(self.limit_location))


@dataclass
class BRParticleSummary:
    """Pass-through summary of particle data counts.

    Build currently only writes these counts as armature custom props —
    full particle instantiation awaits the generator→bone binding
    mechanism (see ``importer/phases/build_blender/helpers/particles.py``
    header note).
    """
    generator_count: int = 0
    texture_count: int = 0
