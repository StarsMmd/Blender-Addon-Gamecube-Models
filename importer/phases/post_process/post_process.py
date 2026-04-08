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
            _select_first_action(armature, actions, mat_slot_indices, pkx_header=pkx_header)

            if include_shiny and shiny_params is not None:
                _apply_shiny(armature, shiny_params, logger)

            if pkx_header is not None:
                _store_pkx_metadata(armature, pkx_header, logger, actions=actions)
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
                _store_pkx_metadata(armature, pkx_header, logger, actions=actions)

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


def _select_first_action(armature, actions, mat_slot_indices, pkx_header=None):
    """Set the armature's active action to its idle animation and sync materials.

    Uses the PKX header's idle animation index (entry 0) if available,
    otherwise falls back to the first action with '_Idle' in the name.
    """
    if not armature.animation_data or not actions:
        return

    active_action = None

    # Try PKX idle index first
    if pkx_header and pkx_header.anim_entries:
        idle_entry = pkx_header.anim_entries[0]
        if idle_entry.sub_anims:
            idle_idx = idle_entry.sub_anims[0].anim_index
            if idle_idx < len(actions):
                active_action = actions[idle_idx]

    # Fallback: find by name
    if active_action is None:
        active_action = next((a for a in actions if '_Idle' in a.name), None)
    if active_action is None:
        active_action = next((a for a in actions if '_Anim_' in a.name or '_Anim ' in a.name), None)
    if active_action is None:
        active_action = actions[0]

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

    Stores routing/brightness as PKX custom properties, then builds shader
    node groups and inserts them into every material globally (matching
    the game's GSmodelEnableColorSwap + GSmodelEnableModulation behavior).

    Args:
        armature: The Blender armature object.
        shiny_params: ShinyParams with route_r/g/b/a (int 0-3) and brightness_r/g/b/a (float).
        logger: Logger instance.
    """
    try:
        from .shiny_filter import (
            build_shiny_route_node_group, build_shiny_bright_node_group,
            setup_shiny_properties, insert_shiny_filter,
            SHINY_ROUTE_GROUP, SHINY_BRIGHT_GROUP,
        )
    except (ImportError, SystemError):
        from importer.phases.post_process.shiny_filter import (
            build_shiny_route_node_group, build_shiny_bright_node_group,
            setup_shiny_properties, insert_shiny_filter,
            SHINY_ROUTE_GROUP, SHINY_BRIGHT_GROUP,
        )

    route = [shiny_params.route_r, shiny_params.route_g,
             shiny_params.route_b, shiny_params.route_a]
    brightness = [shiny_params.brightness_r, shiny_params.brightness_g,
                  shiny_params.brightness_b]  # Alpha forced to max by the game

    route_group = build_shiny_route_node_group(route, SHINY_ROUTE_GROUP)
    bright_group = build_shiny_bright_node_group(brightness, SHINY_BRIGHT_GROUP)
    setup_shiny_properties(armature, route, brightness)
    logger.info("  Built shiny filter node groups: %s, %s", SHINY_ROUTE_GROUP, SHINY_BRIGHT_GROUP)

    count = 0
    for child in armature.children:
        if child.type == 'MESH':
            for mat in child.data.materials:
                if mat and mat.use_nodes:
                    insert_shiny_filter(mat, route_group, bright_group, armature, logger=logger)
                    count += 1

    if count:
        logger.info("  Inserted shiny filter into %d material(s) on %s", count, armature.name)


def _store_pkx_metadata(armature, pkx_header, logger, actions=None):
    """Store PKX header fields as custom properties on the armature.

    Uses dat_pkx_* naming convention. Bone indices are resolved to bone names
    using the armature's bone list. Animation indices are resolved to action
    names when the actions list is available.

    Args:
        armature: The Blender armature object.
        pkx_header: PKXHeader instance from extract phase.
        logger: Logger instance.
        actions: list of Blender Actions in DAT animation order (from Phase 5).
    """
    try:
        from ....shared.helpers.pkx_header import BODY_MAP_NAMES
    except (ImportError, SystemError):
        from shared.helpers.pkx_header import BODY_MAP_NAMES

    h = pkx_header

    # Build DAT animation index → action name mapping
    _index_to_action = {}
    if actions:
        for idx, action in enumerate(actions):
            _index_to_action[idx] = action.name

    def _action_name_for_index(anim_idx):
        """Resolve a DAT animation index to an action name, or empty string."""
        return _index_to_action.get(anim_idx, "")

    _ANIM_TYPE_NAMES = {2: "loop", 3: "hit_reaction", 4: "action", 5: "compound"}
    _SUB_ANIM_TRIGGERS = {0: "sleep_on", 1: "sleep_off", 2: "extra", 3: "unused"}
    _SUB_ANIM_TYPES = {0: "none", 1: "simple", 2: "targeted"}

    # Body map descriptive names (index → property suffix)
    _BODY_MAP_KEYS = [
        "root", "head", "center", "body_3", "neck", "head_top",
        "limb_a", "limb_b", "secondary_8", "secondary_9",
        "secondary_10", "secondary_11", "attach_a", "attach_b",
        "attach_c", "attach_d",
    ]

    # --- Preamble ---
    armature["dat_pkx_format"] = "XD" if h.is_xd else "COLOSSEUM"
    armature["dat_pkx_species_id"] = h.species_id
    armature["dat_pkx_particle_orientation"] = h.particle_orientation
    armature["dat_pkx_distortion_param"] = h.distortion_param
    armature["dat_pkx_distortion_type"] = h.distortion_type
    armature["dat_pkx_model_type"] = "TRAINER" if h.species_id == 0 and h.particle_orientation == 0 else "POKEMON"

    # Flags as individual booleans
    armature["dat_pkx_flag_flying"] = bool(h.flags & 0x01)
    armature["dat_pkx_flag_skip_frac_frames"] = bool(h.flags & 0x04)
    armature["dat_pkx_flag_no_root_anim"] = bool(h.flags & 0x40)
    armature["dat_pkx_flag_bit7"] = bool(h.flags & 0x80)

    # Head bone (resolved to name)
    bones = armature.data.bones
    bone_list = list(bones)
    armature["dat_pkx_head_bone"] = _bone_name_for_index(bone_list, h.head_bone_index)

    # --- Sub-animations (was "part_anim_data") ---
    if h.is_xd:
        for i, pad in enumerate(h.part_anim_data):
            prefix = "dat_pkx_sub_anim_%d" % i
            armature[prefix + "_type"] = _SUB_ANIM_TYPES.get(pad.has_data, "unknown")
            armature[prefix + "_trigger"] = _SUB_ANIM_TRIGGERS.get(i, "unknown")
            armature[prefix + "_anim_ref"] = _action_name_for_index(pad.anim_index_ref) if pad.has_data > 0 else ""
            if pad.has_data == 2:
                # Targeted: store bone names (filter out 0xFF)
                bone_indices = [b for b in pad.bone_config if b != 0xFF]
                bone_names = [_bone_name_for_index(bone_list, idx) for idx in bone_indices]
                armature[prefix + "_bones"] = ', '.join(bone_names) if bone_names else ""
    else:
        for i in range(3):
            prefix = "dat_pkx_sub_anim_%d" % i
            ref = h.colo_part_anim_refs[i]
            armature[prefix + "_type"] = "simple" if ref >= 0 else "none"
            armature[prefix + "_trigger"] = _SUB_ANIM_TRIGGERS.get(i, "unknown")
            armature[prefix + "_anim_ref"] = _action_name_for_index(ref) if ref >= 0 else ""

    # --- Body map bones ---
    first_active = h.anim_entries[0] if h.anim_entries else None
    if first_active:
        for j in range(16):
            bone_idx = first_active.body_map_bones[j]
            key = "dat_pkx_body_%s" % _BODY_MAP_KEYS[j]
            armature[key] = _bone_name_for_index(bone_list, bone_idx)

    # --- Animation entries ---
    armature["dat_pkx_anim_count"] = len(h.anim_entries)
    for i, entry in enumerate(h.anim_entries):
        prefix = "dat_pkx_anim_%02d" % i
        armature[prefix + "_type"] = _ANIM_TYPE_NAMES.get(entry.anim_type, str(entry.anim_type))
        armature[prefix + "_sub_count"] = entry.sub_anim_count
        armature[prefix + "_damage_flags"] = _clamp_int32(entry.damage_flags)
        armature[prefix + "_timing_1"] = entry.timing[0]
        armature[prefix + "_timing_2"] = entry.timing[1]
        armature[prefix + "_timing_3"] = entry.timing[2]
        armature[prefix + "_timing_4"] = entry.timing[3]
        armature[prefix + "_terminator"] = _clamp_int32(entry.terminator)

        for s in range(min(len(entry.sub_anims), 3)):
            sub = entry.sub_anims[s]
            armature[prefix + "_sub_%d_motion" % s] = _clamp_int32(sub.motion_type)
            # Only resolve to action name for active sub-anims; inactive keep empty
            if sub.motion_type > 0:
                armature[prefix + "_sub_%d_anim" % s] = _action_name_for_index(sub.anim_index)
            else:
                armature[prefix + "_sub_%d_anim" % s] = ""

        # Per-entry body map overrides (only when different from model-level)
        if first_active and entry.body_map_bones != first_active.body_map_bones:
            for j in range(16):
                if entry.body_map_bones[j] != first_active.body_map_bones[j]:
                    bone_name = _bone_name_for_index(bone_list, entry.body_map_bones[j])
                    armature[prefix + "_body_%s" % _BODY_MAP_KEYS[j]] = bone_name

    # --- Property descriptions ---
    _add_property_descriptions(armature)

    logger.info("  Stored PKX metadata on %s: format=%s, species=%d, %d anim entries",
                armature.name, armature["dat_pkx_format"], h.species_id, len(h.anim_entries))


def _add_property_descriptions(armature):
    """Add tooltip descriptions to all PKX custom properties."""
    descriptions = {
        "dat_pkx_format": "PKX container format: XD or COLOSSEUM. Determines header layout and timing format.",
        "dat_pkx_species_id": "Pokédex species number. Set to 0 for trainer or generic models.",
        "dat_pkx_model_type": "Animation slot naming: POKEMON uses battle move slots, TRAINER uses pose slots.",
        "dat_pkx_head_bone": "Bone used for head tracking in battle. The game rotates this bone to follow the opponent.",
        "dat_pkx_particle_orientation": "Rotation angle (-2 to 2) for sleep and ice particle effects attached to this model.",
        "dat_pkx_distortion_param": "Visual distortion effect intensity. 0 = no distortion.",
        "dat_pkx_distortion_type": "Visual distortion effect type. 0 = none.",
        "dat_pkx_flag_flying": "Flying mode — enables the Take Flight animation and allows the model to hover.",
        "dat_pkx_flag_skip_frac_frames": "Skip fractional frames — use integer frame stepping for animations.",
        "dat_pkx_flag_no_root_anim": "Remove root joint animation — locks the model's base position in place.",
        "dat_pkx_flag_bit7": "Unknown flag bit 7 (only observed on Espeon).",
        "dat_pkx_shiny_route": "Shiny channel routing [R,G,B,A]. Each value 0-3 selects which source channel (0=Red, 1=Green, 2=Blue, 3=Alpha) feeds that output. Default [0,1,2,3] = no swap.",
        "dat_pkx_shiny_brightness": "Shiny brightness [R,G,B]. Range -1.0 (black) to 1.0 (2× bright), 0.0 = unchanged. Alpha brightness is always forced to maximum by the game.",
        "dat_pkx_anim_count": "Number of animation metadata entries (typically 17 for XD).",
    }

    for prop_name, desc in descriptions.items():
        if prop_name in armature:
            try:
                ui = armature.id_properties_ui(prop_name)
                ui.update(description=desc)
            except (TypeError, AttributeError):
                pass  # Some property types don't support id_properties_ui


def _clamp_int32(value):
    """Clamp a uint32 to signed int32 range for Blender custom properties.

    Values like 0xCDCDCDCD (debug heap fill) exceed Python's C int limit.
    Treat them as 0 since they represent uninitialized data.
    """
    if value > 0x7FFFFFFF:
        return 0
    return int(value)


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
