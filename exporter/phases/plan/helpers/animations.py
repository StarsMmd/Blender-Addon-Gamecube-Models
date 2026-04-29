"""Plan BRAction list into IRBoneAnimationSet list.

Pure — no bpy. During the migration BRAction carries an
IRBoneAnimationSet side-channel built by the legacy unbaker
(see `exporter/phases/describe/helpers/animations.py`); this helper
just unwraps it. When the unbaker migrates fully, plan_actions will
read BRBoneTrack / BRMaterialTrack and produce IRBoneAnimationSet
directly.
"""
try:
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def plan_actions(br_actions, logger=StubLogger()):
    """Convert BRAction list to IRBoneAnimationSet list.

    In: br_actions (list[BRAction]); logger.
    Out: list[IRBoneAnimationSet] in the same order.
    """
    out = []
    for br_action in br_actions:
        ir_set = getattr(br_action, '_ir_animation_set', None)
        if ir_set is None:
            raise ValueError(
                "plan_actions: BRAction '%s' has no _ir_animation_set; "
                "the unbaker hasn't been migrated into plan yet."
                % br_action.name
            )
        out.append(ir_set)
    return out
