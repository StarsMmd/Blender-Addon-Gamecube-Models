import bpy

from ...Node import Node
from ....Constants import *
from ....IO.Logger import NullLogger
from ..Animation.Frame import read_fobjdesc

# Mapping: HSD material animation track type → (shader node name, component index)
_mat_color_map = {
    HSD_A_M_DIFFUSE_R:  ('DiffuseColor', 0),
    HSD_A_M_DIFFUSE_G:  ('DiffuseColor', 1),
    HSD_A_M_DIFFUSE_B:  ('DiffuseColor', 2),
    HSD_A_M_ALPHA:      ('AlphaValue',   0),
}

# sRGB tracks that need linearization (RGB channels, not alpha)
_srgb_tracks = {HSD_A_M_DIFFUSE_R, HSD_A_M_DIFFUSE_G, HSD_A_M_DIFFUSE_B}


def _srgb_to_linear_single(c):
    """Convert a single sRGB channel value (0-1) to linear."""
    if c <= 0.0404482362771082:
        return c / 12.92
    else:
        return pow((c + 0.055) / 1.055, 2.4)


# Material Animation
class MaterialAnimation(Node):
    class_name = "Material Animation"
    fields = [
        ('next', 'MaterialAnimation'),
        ('animation', 'Animation'),
        ('texture_animation', 'TextureAnimation'),
        ('render_animation', 'RenderAnimation'),
    ]

    def build(self, mobject, action_name_base, builder):
        """
        mobject:          the MaterialObject node (has .blender_material)
        action_name_base: base name for the action
        builder:          ModelBuilder
        """
        logger = builder.logger
        mat = mobject.blender_material
        max_frame = builder.options.get("max_frame", 1000)

        logger.debug("  MatAnim build: material='%s' has_aobj=%s has_texanim=%s",
                     mat.name, self.animation is not None,
                     self.texture_animation is not None)

        # Ensure the material has animation data and an action
        action = _get_or_create_action(mat, action_name_base, builder)

        # Process material color/alpha tracks
        if self.animation and not (self.animation.flags & AOBJ_NO_ANIM):
            aobj = self.animation
            fobj = aobj.frame
            while fobj:
                _apply_material_track(fobj, aobj, mat, action, max_frame, logger)
                fobj = fobj.next

        # Process texture animation tracks
        if self.texture_animation:
            tex_anim = self.texture_animation
            while tex_anim:
                tex_anim.build(mobject, action, builder)
                tex_anim = tex_anim.next


def _get_or_create_action(material, action_name_base, builder):
    """Ensure the Blender material has animation_data with an action."""
    from ....BlenderVersion import BlenderVersion

    if not material.animation_data:
        material.animation_data_create()
    if not material.animation_data.action:
        action_name = action_name_base + '_' + material.name if material.name else action_name_base + '_mat'
        action = bpy.data.actions.new(action_name)
        action.use_fake_user = True
        material.animation_data.action = action

        # Action slots for Blender 4.5+
        if bpy.app.version >= BlenderVersion(4, 5, 0):
            action.slots.new('MATERIAL', material.name or 'Material')
            action.slots.active = action.slots[0]
            material.animation_data.action_slot = action.slots[0]

    return material.animation_data.action


def _apply_material_track(fobj, aobj, material, action, max_frame, logger=NullLogger()):
    """Create fcurves for a single material color/alpha animation track."""
    mapping = _mat_color_map.get(fobj.type)
    if not mapping:
        logger.debug("    MatAnim: skipping track type %d (ambient/specular/unknown)", fobj.type)
        return

    node_name, index = mapping

    # Find the target node in the material's shader tree
    if node_name not in material.node_tree.nodes:
        logger.warning("    MatAnim: node '%s' not found in material '%s'", node_name, material.name)
        return

    needs_linearize = fobj.type in _srgb_tracks

    data_path = 'node_tree.nodes["%s"].outputs[0].default_value' % node_name

    # Skip if this fcurve already exists (e.g. same material animated by multiple anim indices)
    if action.fcurves.find(data_path, index=index):
        logger.debug("    MatAnim: fcurve %s[%d] already exists, skipping", data_path, index)
        return

    if needs_linearize:
        # Bake with sRGB→linear conversion:
        # 1. Decode into temp fcurve with scale=1/255
        # 2. Sample each frame, apply sRGB→linear
        # 3. Write to final fcurve
        temp_curve = action.fcurves.new(data_path + '_temp', index=index)
        read_fobjdesc(fobj, temp_curve, 0, 1.0 / 255.0)

        curve = action.fcurves.new(data_path, index=index)
        end = min(int(aobj.end_frame), max_frame) if max_frame else int(aobj.end_frame)
        for frame in range(end + 1):
            val = temp_curve.evaluate(frame)
            linear_val = _srgb_to_linear_single(max(0.0, min(1.0, val)))
            curve.keyframe_points.insert(frame, linear_val).interpolation = 'LINEAR'

        action.fcurves.remove(temp_curve)
        logger.debug("    MatAnim: baked sRGB→linear track %s[%d] (%d frames)",
                     node_name, index, end + 1)
    else:
        # Alpha: direct decode, no sRGB conversion needed
        curve = action.fcurves.new(data_path, index=index)
        read_fobjdesc(fobj, curve, 0, 1.0 / 255.0)
        logger.debug("    MatAnim: direct track %s[%d]", node_name, index)

    if aobj.flags & AOBJ_ANIM_LOOP:
        curve.modifiers.new('CYCLES')
