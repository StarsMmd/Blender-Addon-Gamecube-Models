"""Plan BRConstraints into the six IR constraint lists. Pure 1:1 unwrap."""
try:
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def plan_constraints(br_constraints, logger=StubLogger()):
    """Out: tuple of (ik, copy_location, track_to, copy_rotation,
    limit_rotation, limit_location) — same shape as the legacy
    describe_constraints return value."""
    return (
        br_constraints.ik,
        br_constraints.copy_location,
        br_constraints.track_to,
        br_constraints.copy_rotation,
        br_constraints.limit_rotation,
        br_constraints.limit_location,
    )
