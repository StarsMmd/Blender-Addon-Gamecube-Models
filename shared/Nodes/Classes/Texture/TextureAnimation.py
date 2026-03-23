from ...Node import Node
from ....Constants import *
from ....IO.Logger import NullLogger
from ..Animation.Frame import read_fobjdesc

# Mapping: HSD texture animation track type → (Mapping node input index, component index)
# Mapping node inputs: 0=Vector, 1=Location, 2=Rotation, 3=Scale
_tex_uv_map = {
    HSD_A_T_TRAU: (1, 0),  # Location X
    HSD_A_T_TRAV: (1, 1),  # Location Y
    HSD_A_T_SCAU: (3, 0),  # Scale X
    HSD_A_T_SCAV: (3, 1),  # Scale Y
    HSD_A_T_ROTX: (2, 0),  # Rotation X
    HSD_A_T_ROTY: (2, 1),  # Rotation Y
    HSD_A_T_ROTZ: (2, 2),  # Rotation Z
}


# Texture Animation
class TextureAnimation(Node):
    class_name = "Texture Animation"
    fields = [
        ('next', 'TextureAnimation'),
        ('id', 'uint'),
        ('animation', 'Animation'),
        ('image_table', '*(Image[image_table_count])'),
        ('palette_table', '*(Palette[palette_table_count])'),
        ('image_table_count', 'ushort'),
        ('palette_table_count', 'ushort'),
    ]

    def build(self, mobject, action, builder):
        """
        mobject: the MaterialObject node (has .blender_material and .texture chain)
        action:  the Blender action to add fcurves to
        builder: ModelBuilder
        """
        logger = builder.logger
        mat = mobject.blender_material

        # Find the texture node matching this animation's id by walking the texture chain
        texture = mobject.texture
        tex_index = 0
        while texture and tex_index < self.id:
            texture = texture.next
            tex_index += 1

        if not texture:
            logger.warning("    TexAnim: texture index %d not found on material '%s'",
                           self.id, mat.name)
            return

        mapping_name = 'Mapping_0x%X' % texture.id

        if mapping_name not in mat.node_tree.nodes:
            logger.warning("    TexAnim: node '%s' not found in material '%s'",
                           mapping_name, mat.name)
            return

        logger.debug("    TexAnim: id=%d texture=0x%X mapping=%s has_aobj=%s",
                     self.id, texture.id, mapping_name,
                     self.animation is not None)

        if not self.animation or (self.animation.flags & AOBJ_NO_ANIM):
            return

        aobj = self.animation
        fobj = aobj.frame
        while fobj:
            uv_mapping = _tex_uv_map.get(fobj.type)
            if uv_mapping:
                input_index, component = uv_mapping
                data_path = 'node_tree.nodes["%s"].inputs[%d].default_value' % (mapping_name, input_index)
                curve = action.fcurves.find(data_path, index=component)
                if curve:
                    logger.debug("    TexAnim: fcurve %s[%d] already exists, skipping",
                                 data_path, component)
                    fobj = fobj.next
                    continue
                curve = action.fcurves.new(data_path, index=component)
                read_fobjdesc(fobj, curve, 0, 1)

                if aobj.flags & AOBJ_ANIM_LOOP:
                    curve.modifiers.new('CYCLES')

                # Debug: dump all keyframe values
                kf_data = [(kp.co[0], kp.co[1], kp.interpolation) for kp in curve.keyframe_points]
                logger.debug("    TexAnim: track type=%d → %s input[%d][%d] | %d keyframes: %s",
                             fobj.type, mapping_name, input_index, component,
                             len(kf_data), kf_data)

            elif fobj.type == HSD_A_T_TIMG:
                logger.debug("    TexAnim: TIMG (texture swap) not yet implemented")
            elif fobj.type == HSD_A_T_TCLT:
                logger.debug("    TexAnim: TCLT (palette swap) not yet implemented")
            else:
                logger.debug("    TexAnim: skipping track type %d", fobj.type)

            fobj = fobj.next
