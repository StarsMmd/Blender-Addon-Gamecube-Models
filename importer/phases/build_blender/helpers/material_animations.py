"""Material animation helpers for building Blender fcurves.

Provides functions to write material color/alpha and texture UV keyframes
into fcurves, targeting shader node values (DiffuseColor, AlphaValue,
Mapping node inputs).

Functions accept an `fcurves` collection which can be either
`action.fcurves` (legacy) or `channelbag.fcurves` (slotted actions).
"""
import bpy

# Mapping from IR field → (shader node name, component index)
COLOR_TRACK_MAP = {
    'diffuse_r': ('DiffuseColor', 0),
    'diffuse_g': ('DiffuseColor', 1),
    'diffuse_b': ('DiffuseColor', 2),
    'alpha':     ('AlphaValue',   0),
}

# Mapping from IRTextureUVTrack field → (Mapping node input index, component index)
UV_TRACK_MAP = {
    'translation_u': (1, 0),
    'translation_v': (1, 1),
    'scale_u':       (3, 0),
    'scale_v':       (3, 1),
    'rotation_x':    (2, 0),
    'rotation_y':    (2, 1),
    'rotation_z':    (2, 2),
}


def apply_color_tracks(track, material, fcurves, max_frame, logger):
    """Insert color/alpha keyframes into fcurves."""
    for field_name, (node_name, index) in COLOR_TRACK_MAP.items():
        keyframes = getattr(track, field_name)
        if not keyframes:
            continue

        if node_name not in material.node_tree.nodes:
            continue

        data_path = 'node_tree.nodes["%s"].outputs[0].default_value' % node_name
        curve = fcurves.new(data_path, index=index)

        for kf in keyframes:
            point = curve.keyframe_points.insert(kf.frame, kf.value)
            point.interpolation = kf.interpolation.value

        if track.loop:
            curve.modifiers.new('CYCLES')

        logger.debug("    MatAnim: %s[%d] → %d keyframes", node_name, index, len(keyframes))


def apply_texture_uv_tracks(track, material, fcurves, logger):
    """Insert texture UV animation keyframes into fcurves."""
    for uv_track in track.texture_uv_tracks:
        mapping_node = find_mapping_node(material, uv_track.texture_index)
        if not mapping_node:
            continue

        mapping_name = mapping_node.name

        for field_name, (input_index, component) in UV_TRACK_MAP.items():
            keyframes = getattr(uv_track, field_name)
            if not keyframes:
                continue

            data_path = 'node_tree.nodes["%s"].inputs[%d].default_value' % (mapping_name, input_index)
            curve = fcurves.new(data_path, index=component)

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


def find_mapping_node(material, texture_index):
    """Find the Mapping shader node for a given texture index."""
    target_name = 'Mapping_%d' % texture_index
    return material.node_tree.nodes.get(target_name)
