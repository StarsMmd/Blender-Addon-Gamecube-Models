"""Phase 6 — Post-Processing: reset poses, select first animation, apply shiny filters.

Runs after either the new IR pipeline (Phase 5) or the legacy importer.
Operates entirely on Blender objects — no dependency on earlier phases.

Shiny filter injection is handled here as a post-processing step, independent
of what happened in earlier phases. Like the standalone shiny script, this phase
can inject shiny shaders into any model's materials given the raw PKX parameters.
"""
import bpy

try:
    from ....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def post_process(armature_names, shiny_params=None, options=None, logger=StubLogger(),
                 build_results=None):
    """Post-process imported models: reset poses, select animations, apply shiny.

    Args:
        armature_names: set of armature object names to post-process (used for legacy path).
        shiny_params: ShinyParams from Phase 1 extract, or None.
        options: dict of importer options (checks include_shiny). None = shiny enabled.
        logger: Logger instance.
        build_results: list of dicts from Phase 5 with armature/actions/mat_slot_indices.
            When provided, uses these directly instead of rediscovering actions by name.
    """
    logger.info("=== Phase 6: Post-Processing ===")
    logger.info("  Shiny params: %s", shiny_params is not None)
    logger.info("  Options: %s", options)

    include_shiny = True if options is None else options.get("include_shiny", True)

    if build_results:
        # New pipeline path: use actions directly from Phase 5
        for result in build_results:
            armature = result['armature']
            actions = result['actions']
            mat_slot_indices = result['mat_slot_indices']

            logger.info("  Post-processing armature: %s (%d actions)", armature.name, len(actions))
            _select_first_action(armature, actions, mat_slot_indices)

            if include_shiny and shiny_params is not None:
                _apply_shiny(armature, shiny_params, logger)
    else:
        # Legacy path: discover actions by name matching
        logger.info("  Armatures: %s", armature_names)
        for name in armature_names:
            armature = bpy.data.objects.get(name)
            if not armature or armature.type != 'ARMATURE':
                continue

            actions = _find_actions(armature)
            mat_slot_indices = _find_material_slot_indices(armature, actions)
            _select_first_action(armature, actions, mat_slot_indices)

            if include_shiny and shiny_params is not None:
                _apply_shiny(armature, shiny_params, logger)

    bpy.context.scene.frame_set(0)
    logger.info("=== Phase 6 complete ===")


def _find_actions(armature):
    """Find all actions that have an OBJECT slot targeting this armature."""
    actions = []
    for action in bpy.data.actions:
        for slot in action.slots:
            if slot.target_id_type == 'OBJECT' and slot.handle == getattr(
                    armature.animation_data, 'action_slot_handle', None):
                actions.append(action)
                break
        else:
            # Fallback: match by name prefix for legacy-created actions
            arm_prefix = armature.name.replace('Armature_', '')
            if action.name.startswith(arm_prefix):
                actions.append(action)
    return actions


def _find_material_slot_indices(armature, actions):
    """Reconstruct material → slot index mapping from existing action slots.

    Looks at the first action's MATERIAL slots and matches them to materials
    in the scene by name.
    """
    if not actions:
        return {}

    action = actions[0]
    mat_slot_indices = {}
    for idx, slot in enumerate(action.slots):
        if slot.target_id_type == 'MATERIAL':
            mat = bpy.data.materials.get(slot.identifier)
            if mat:
                mat_slot_indices[mat] = idx

    return mat_slot_indices


def _select_first_action(armature, actions, mat_slot_indices):
    """Set the armature's active action to its first animation and sync materials."""
    if not armature.animation_data or not actions:
        return

    first_anim = next((a for a in actions if '_Anim_' in a.name or '_Anim ' in a.name), None)
    active_action = first_anim or actions[0]
    armature.animation_data.action = active_action

    for mat, slot_idx in mat_slot_indices.items():
        if not mat.animation_data:
            continue
        mat.animation_data.action = active_action
        if slot_idx < len(active_action.slots):
            mat.animation_data.action_slot = active_action.slots[slot_idx]

    if mat_slot_indices:
        _register_action_sync_handler(armature, mat_slot_indices)


def _apply_shiny(armature, shiny_params, logger):
    """Build the shiny filter node group and inject it into all materials.

    Args:
        armature: The Blender armature object.
        shiny_params: ShinyParams with route_r/g/b/a (int 0-3) and brightness_r/g/b/a (float).
        logger: Logger instance.
    """
    try:
        from .shiny_filter import (
            build_shiny_node_group, setup_shiny_properties, insert_shiny_filter,
        )
    except (ImportError, SystemError):
        from importer.phases.post_process.shiny_filter import (
            build_shiny_node_group, setup_shiny_properties, insert_shiny_filter,
        )

    try:
        from ....shared.IR.shiny import IRShinyFilter
        from ....shared.IR.enums import ShinyChannel
    except (ImportError, SystemError):
        from shared.IR.shiny import IRShinyFilter
        from shared.IR.enums import ShinyChannel

    channel_map = {0: ShinyChannel.RED, 1: ShinyChannel.GREEN, 2: ShinyChannel.BLUE, 3: ShinyChannel.ALPHA}
    routing = (
        channel_map.get(shiny_params.route_r, ShinyChannel.RED),
        channel_map.get(shiny_params.route_g, ShinyChannel.GREEN),
        channel_map.get(shiny_params.route_b, ShinyChannel.BLUE),
        channel_map.get(shiny_params.route_a, ShinyChannel.ALPHA),
    )
    brightness = (
        shiny_params.brightness_r,
        shiny_params.brightness_g,
        shiny_params.brightness_b,
        shiny_params.brightness_a,
    )
    ir_filter = IRShinyFilter(channel_routing=routing, brightness=brightness)

    model_name = armature.name.replace('Armature_', '')
    group_name = "ShinyFilter_%s" % model_name
    node_group = build_shiny_node_group(ir_filter, group_name)
    setup_shiny_properties(armature, ir_filter, group_name)
    logger.info("  Built shiny filter node group: %s", group_name)

    count = 0
    for child in armature.children:
        if child.type == 'MESH':
            for mat in child.data.materials:
                if mat and mat.use_nodes:
                    insert_shiny_filter(mat, node_group, armature, logger=logger)
                    count += 1

    if count:
        logger.info("  Inserted shiny filter into %d material(s) on %s", count, armature.name)


def _register_action_sync_handler(armature, mat_slot_indices):
    """Register a depsgraph handler that syncs material actions when the armature's action changes."""
    armature_name = armature.name
    mat_info = [(mat.name, slot_idx) for mat, slot_idx in mat_slot_indices.items()]
    last_action = [armature.animation_data.action]

    def on_depsgraph_update(scene):
        arm = bpy.data.objects.get(armature_name)
        if not arm or not arm.animation_data or not arm.animation_data.action:
            return
        current_action = arm.animation_data.action
        if current_action == last_action[0]:
            return
        last_action[0] = current_action

        for mat_name, slot_idx in mat_info:
            mat = bpy.data.materials.get(mat_name)
            if not mat or not mat.animation_data:
                continue
            if slot_idx < len(current_action.slots):
                mat.animation_data.action = current_action
                mat.animation_data.action_slot = current_action.slots[slot_idx]

    for handler in list(bpy.app.handlers.depsgraph_update_post):
        if hasattr(handler, '_dat_sync_armature') and handler._dat_sync_armature == armature_name:
            bpy.app.handlers.depsgraph_update_post.remove(handler)

    on_depsgraph_update._dat_sync_armature = armature_name
    bpy.app.handlers.depsgraph_update_post.append(on_depsgraph_update)
