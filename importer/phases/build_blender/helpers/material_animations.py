"""Build Blender material animations from IRMaterialAnimationSet.

Creates actions with fcurves targeting shader node values (DiffuseColor,
AlphaValue, Mapping node inputs) and pushes them into NLA tracks.
"""
import bpy

try:
    from .....shared.helpers.logger import StubLogger
    from .....shared.BlenderVersion import BlenderVersion
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger
    from shared.BlenderVersion import BlenderVersion

# Mapping from IR field → (shader node name, component index)
_COLOR_TRACK_MAP = {
    'diffuse_r': ('DiffuseColor', 0),
    'diffuse_g': ('DiffuseColor', 1),
    'diffuse_b': ('DiffuseColor', 2),
    'alpha':     ('AlphaValue',   0),
}

# Mapping from IRTextureUVTrack field → (Mapping node input index, component index)
_UV_TRACK_MAP = {
    'translation_u': (1, 0),
    'translation_v': (1, 1),
    'scale_u':       (3, 0),
    'scale_v':       (3, 1),
    'rotation_x':    (2, 0),
    'rotation_y':    (2, 1),
    'rotation_z':    (2, 2),
}


def build_material_animations(ir_model, material_lookup, options, logger=StubLogger()):
    """Create Blender material animation actions from IRMaterialAnimationSet list.

    Args:
        ir_model: IRModel with material_animations populated.
        material_lookup: dict mapping mesh_name → bpy.types.Material (from build phase).
        options: importer options dict.
        logger: Logger instance.
    """
    max_frame = options.get("max_frame", 1000)

    for anim_set in ir_model.material_animations:
        for track in anim_set.tracks:
            mat = material_lookup.get(track.material_mesh_name)
            if not mat:
                continue

            action = _create_action(mat, anim_set.name)
            _apply_color_tracks(track, mat, action, max_frame, logger)
            _apply_texture_uv_tracks(track, mat, action, logger)

            if len(action.fcurves) == 0:
                bpy.data.actions.remove(action)
            else:
                # Push into NLA track
                nla_track = mat.animation_data.nla_tracks.new()
                nla_track.name = action.name
                nla_track.mute = True
                strip = nla_track.strips.new(action.name, 0, action)
                strip.extrapolation = 'HOLD'
                mat.animation_data.action = None

        logger.info("  Material animation '%s': %d tracks", anim_set.name, len(anim_set.tracks))


def _create_action(material, action_name_base):
    """Create a new Blender action for material animation."""
    if not material.animation_data:
        material.animation_data_create()

    action_name = '%s_%s' % (action_name_base, material.name or 'mat')
    action = bpy.data.actions.new(action_name)
    action.use_fake_user = True
    material.animation_data.action = action

    if bpy.app.version >= BlenderVersion(4, 5, 0):
        action.slots.new('MATERIAL', material.name or 'Material')
        action.slots.active = action.slots[0]
        material.animation_data.action_slot = action.slots[0]

    return action


def _apply_color_tracks(track, material, action, max_frame, logger):
    """Insert color/alpha keyframes into the action."""
    for field_name, (node_name, index) in _COLOR_TRACK_MAP.items():
        keyframes = getattr(track, field_name)
        if not keyframes:
            continue

        if node_name not in material.node_tree.nodes:
            continue

        data_path = 'node_tree.nodes["%s"].outputs[0].default_value' % node_name
        curve = action.fcurves.new(data_path, index=index)

        for kf in keyframes:
            point = curve.keyframe_points.insert(kf.frame, kf.value)
            point.interpolation = kf.interpolation.value

        if track.loop:
            curve.modifiers.new('CYCLES')

        logger.debug("    MatAnim: %s[%d] → %d keyframes", node_name, index, len(keyframes))


def _apply_texture_uv_tracks(track, material, action, logger):
    """Insert texture UV animation keyframes into the action."""
    for uv_track in track.texture_uv_tracks:
        # Find the Mapping node for this texture index
        # Convention: nodes are named 'Mapping_0x{texture_address:X}'
        # We need to find the nth mapping node by texture index
        mapping_node = _find_mapping_node(material, uv_track.texture_index)
        if not mapping_node:
            continue

        mapping_name = mapping_node.name

        for field_name, (input_index, component) in _UV_TRACK_MAP.items():
            keyframes = getattr(uv_track, field_name)
            if not keyframes:
                continue

            data_path = 'node_tree.nodes["%s"].inputs[%d].default_value' % (mapping_name, input_index)
            curve = action.fcurves.new(data_path, index=component)

            for kf in keyframes:
                point = curve.keyframe_points.insert(kf.frame, kf.value)
                point.interpolation = kf.interpolation.value
                if kf.handle_left:
                    point.handle_left[:] = kf.handle_left
                if kf.handle_right:
                    point.handle_right[:] = kf.handle_right

            if track.loop:
                curve.modifiers.new('CYCLES')

            logger.debug("    TexAnim: %s input[%d][%d] → %d keyframes",
                         mapping_name, input_index, component, len(keyframes))


def _find_mapping_node(material, texture_index):
    """Find the Mapping shader node for a given texture index."""
    target_name = 'Mapping_%d' % texture_index
    return material.node_tree.nodes.get(target_name)
