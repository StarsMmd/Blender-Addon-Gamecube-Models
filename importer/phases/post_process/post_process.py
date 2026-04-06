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
                 build_results=None, pkx_header=None):
    """Post-process imported models: reset poses, select animations, apply shiny, store PKX metadata.

    Args:
        armature_names: set of armature object names to post-process (used for legacy path).
        shiny_params: ShinyParams from Phase 1 extract, or None.
        options: dict of importer options (checks include_shiny). None = shiny enabled.
        logger: Logger instance.
        build_results: list of dicts from Phase 5 with armature/actions/mat_slot_indices.
            When provided, uses these directly instead of rediscovering actions by name.
        pkx_header: PKXHeader from Phase 1 extract, or None.
    """
    logger.info("=== Phase 6: Post-Processing ===")
    logger.info("  Shiny params: %s", shiny_params is not None)
    logger.info("  PKX header: %s", pkx_header is not None)
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

            if pkx_header is not None:
                _store_pkx_metadata(armature, pkx_header, logger)
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

            if pkx_header is not None:
                _store_pkx_metadata(armature, pkx_header, logger)

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
            build_shiny_route_node_group, build_shiny_bright_node_group,
            setup_shiny_properties, insert_shiny_filter,
        )
    except (ImportError, SystemError):
        from importer.phases.post_process.shiny_filter import (
            build_shiny_route_node_group, build_shiny_bright_node_group,
            setup_shiny_properties, insert_shiny_filter,
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
    route_name = "ShinyRoute_%s" % model_name
    bright_name = "ShinyBright_%s" % model_name
    route_group = build_shiny_route_node_group(ir_filter, route_name)
    bright_group = build_shiny_bright_node_group(ir_filter, bright_name)
    setup_shiny_properties(armature, ir_filter, route_name, bright_name)
    logger.info("  Built shiny filter node groups: %s, %s", route_name, bright_name)

    count = 0
    for child in armature.children:
        if child.type == 'MESH':
            for mat in child.data.materials:
                if mat and mat.use_nodes:
                    insert_shiny_filter(mat, route_group, bright_group, armature, logger=logger)
                    count += 1

    if count:
        logger.info("  Inserted shiny filter into %d material(s) on %s", count, armature.name)


def _store_pkx_metadata(armature, pkx_header, logger):
    """Store PKX header fields as custom properties on the armature.

    Uses dat_pkx_* naming convention. Bone indices are resolved to bone names
    using the armature's bone list.

    Args:
        armature: The Blender armature object.
        pkx_header: PKXHeader instance from extract phase.
        logger: Logger instance.
    """
    try:
        from ....shared.helpers.pkx_header import NULL_JOINT_NAMES
    except (ImportError, SystemError):
        from shared.helpers.pkx_header import NULL_JOINT_NAMES

    h = pkx_header

    # Preamble
    armature["dat_pkx_format"] = "XD" if h.is_xd else "COLOSSEUM"
    armature["dat_pkx_species_id"] = h.species_id
    armature["dat_pkx_particle_orientation"] = h.particle_orientation
    armature["dat_pkx_flags"] = h.flags
    armature["dat_pkx_distortion_param"] = h.distortion_param
    armature["dat_pkx_distortion_type"] = h.distortion_type
    armature["dat_pkx_model_type"] = "TRAINER" if h.species_id == 0 and h.particle_orientation == 0 else "POKEMON"

    # Resolve head bone index to name
    bones = armature.data.bones
    bone_list = list(bones)
    armature["dat_pkx_head_bone"] = _bone_name_for_index(bone_list, h.head_bone_index)

    # Shiny routing + brightness (raw values for PKX header reconstruction)
    armature["dat_pkx_shiny_route"] = list(h.shiny_route)
    armature["dat_pkx_shiny_brightness"] = list(h.shiny_brightness)

    # Part animation data (XD only)
    if h.is_xd:
        for i, pad in enumerate(h.part_anim_data):
            prefix = "dat_pkx_part_%d" % i
            armature[prefix + "_has_data"] = pad.has_data
            armature[prefix + "_sub_param"] = pad.sub_param
            armature[prefix + "_bone_config"] = pad.bone_config.hex()
            armature[prefix + "_anim_ref"] = pad.anim_index_ref
    else:
        for i in range(3):
            armature["dat_pkx_colo_part_ref_%d" % i] = h.colo_part_anim_refs[i]

    # Null joint bones (model-level, from first active entry)
    first_active = h.anim_entries[0] if h.anim_entries else None
    if first_active:
        for j in range(16):
            bone_idx = first_active.null_joint_bones[j]
            armature["dat_pkx_null_bone_%d" % j] = _bone_name_for_index(bone_list, bone_idx)

    # Animation metadata entries
    armature["dat_pkx_anim_count"] = len(h.anim_entries)
    for i, entry in enumerate(h.anim_entries):
        prefix = "dat_pkx_anim_%02d" % i
        armature[prefix + "_type"] = entry.anim_type
        armature[prefix + "_sub_count"] = entry.sub_anim_count
        armature[prefix + "_damage_flags"] = entry.damage_flags
        armature[prefix + "_timing_1"] = entry.timing[0]
        armature[prefix + "_timing_2"] = entry.timing[1]
        armature[prefix + "_timing_3"] = entry.timing[2]
        armature[prefix + "_timing_4"] = entry.timing[3]
        armature[prefix + "_terminator"] = entry.terminator

        # Sub-animations
        for s in range(min(len(entry.sub_anims), 3)):
            armature[prefix + "_sub_%d_motion" % s] = entry.sub_anims[s].motion_type
            armature[prefix + "_sub_%d_anim" % s] = entry.sub_anims[s].anim_index

        # Per-entry null joint bone overrides (only if different from model-level)
        if first_active and entry.null_joint_bones != first_active.null_joint_bones:
            for j in range(16):
                if entry.null_joint_bones[j] != first_active.null_joint_bones[j]:
                    bone_name = _bone_name_for_index(bone_list, entry.null_joint_bones[j])
                    armature[prefix + "_bone_%d" % j] = bone_name

    logger.info("  Stored PKX metadata on %s: format=%s, species=%d, %d anim entries",
                armature.name, armature["dat_pkx_format"], h.species_id, len(h.anim_entries))


def _bone_name_for_index(bone_list, index):
    """Resolve a bone index to a bone name. Returns '' for -1 or out-of-range."""
    if index < 0 or index >= len(bone_list):
        return ""
    return bone_list[index].name


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
