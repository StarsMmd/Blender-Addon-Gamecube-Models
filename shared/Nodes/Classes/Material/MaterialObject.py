import bpy
import math

from ...Node import Node
from ....Errors import *
from ....Constants import *

# Material Object
class MaterialObject(Node):
    class_name = "Material Object"
    fields = [
        ('class_type', 'string'),
        ('render_mode', 'uint'),
        ('texture', 'Texture'),
        ('material', 'Material'),
        ('render_data', 'Render'),
        ('pixel_engine_data', 'PixelEngine'),
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        self.id = self.address

    def build(self, builder, joint_flags=0):
        self.logger = builder.logger

        material = self.material
        blender_material = bpy.data.materials.new('')
        blender_material.use_nodes = True
        nodes = blender_material.node_tree.nodes
        links = blender_material.node_tree.links

        for node in nodes:
            nodes.remove(node)
        output = nodes.new('ShaderNodeOutputMaterial')

        diffuse_color = material.diffuse.asRGBAList()

        self.logger.debug('--- MOBJ 0x%X ---', self.address)
        self.logger.debug('  rendermode: 0x%08X  RENDER_DIFFUSE=%s  diffuse_bits=%d  alpha_bits=%d',
            self.render_mode,
            bool(self.render_mode & RENDER_DIFFUSE),
            self.render_mode & RENDER_DIFFUSE_BITS,
            (self.render_mode & RENDER_ALPHA_BITS) >> RENDER_ALPHA_SHIFT)
        self.logger.debug('  diffuse_color (linearized): [%.4f, %.4f, %.4f, %.4f]  mat.alpha=%.4f',
            *diffuse_color, material.alpha)

        textures = []
        texture_number = 0
        texture = self.texture
        # Note: there shouldn't be more than 7 textures per material
        while texture:
            # Check if texture is enabled in the material
            if self.render_mode & (1 << (texture_number + 4)):
                texture.build(builder)
                textures.append(texture)
            texture = texture.next
            texture_number += 1
            if texture_number > 7:
                break

        alpha = None
        diffuse_flags = self.render_mode & RENDER_DIFFUSE_BITS
        if diffuse_flags == RENDER_DIFFUSE_MAT0:
            diffuse_flags = RENDER_DIFFUSE_MAT
        
        alpha_flags = self.render_mode & RENDER_ALPHA_BITS
        if alpha_flags == RENDER_ALPHA_COMPAT:
            alpha_flags = diffuse_flags << RENDER_ALPHA_SHIFT

        diffuse_names = {RENDER_DIFFUSE_MAT0: 'MAT0', RENDER_DIFFUSE_MAT: 'MAT',
                         RENDER_DIFFUSE_VTX: 'VTX', RENDER_DIFFUSE_BOTH: 'BOTH'}
        alpha_names = {RENDER_ALPHA_COMPAT: 'COMPAT', RENDER_ALPHA_MAT: 'MAT',
                       RENDER_ALPHA_VTX: 'VTX', RENDER_ALPHA_BOTH: 'BOTH'}

        if self.render_mode & RENDER_DIFFUSE:
            # RENDER_DIFFUSE set: VTX modes use white (vertex color applied post-texture),
            # MAT/BOTH modes use the material diffuse color.
            color = nodes.new('ShaderNodeRGB')
            if diffuse_flags == RENDER_DIFFUSE_VTX:
                color.outputs[0].default_value[:] = [1,1,1,1]
                self.logger.debug('  base color: RENDER_DIFFUSE=1, diffuse=%s → white [1,1,1,1]',
                    diffuse_names.get(diffuse_flags, hex(diffuse_flags)))
            else:
                color.outputs[0].default_value[:] = diffuse_color
                self.logger.debug('  base color: RENDER_DIFFUSE=1, diffuse=%s → mat color %s',
                    diffuse_names.get(diffuse_flags, hex(diffuse_flags)), diffuse_color)

            alpha = nodes.new('ShaderNodeValue')
            if alpha_flags == RENDER_ALPHA_VTX:
                alpha.outputs[0].default_value = 1
                self.logger.debug('  base alpha: alpha=%s → 1.0',
                    alpha_names.get(alpha_flags, hex(alpha_flags)))
            else:
                alpha.outputs[0].default_value = material.alpha
                self.logger.debug('  base alpha: alpha=%s → mat alpha %.3f',
                    alpha_names.get(alpha_flags, hex(alpha_flags)), material.alpha)
        else:
            # RENDER_DIFFUSE not set: vertex color is the base, material color is additive
            if diffuse_flags == RENDER_DIFFUSE_MAT:
                color = nodes.new('ShaderNodeRGB')
                color.outputs[0].default_value[:] = diffuse_color
                self.logger.debug('  base color: RENDER_DIFFUSE=0, diffuse=MAT → mat color %s',
                    diffuse_color)
            else:
                color = nodes.new('ShaderNodeAttribute')
                color.attribute_name = 'color_0'
                if diffuse_flags != RENDER_DIFFUSE_VTX:
                    diff = nodes.new('ShaderNodeRGB')
                    diff.outputs[0].default_value[:] = diffuse_color
                    mix = nodes.new('ShaderNodeMixRGB')
                    mix.blend_type = 'ADD'
                    mix.inputs[0].default_value = 1
                    links.new(color.outputs[0], mix.inputs[1])
                    links.new(diff.outputs[0], mix.inputs[2])
                    color = mix
                    self.logger.debug('  base color: RENDER_DIFFUSE=0, diffuse=%s → vtx_color + mat color %s',
                        diffuse_names.get(diffuse_flags, hex(diffuse_flags)), diffuse_color)
                else:
                    self.logger.debug('  base color: RENDER_DIFFUSE=0, diffuse=VTX → vtx_color attribute only')

            if alpha_flags == RENDER_ALPHA_MAT:
                alpha = nodes.new('ShaderNodeValue')
                alpha.outputs[0].default_value = material.alpha
                self.logger.debug('  base alpha: RENDER_DIFFUSE=0, alpha=MAT → mat alpha %.3f',
                    material.alpha)
            else:
                alpha = nodes.new('ShaderNodeAttribute')
                alpha.attribute_name = 'alpha_0'
                if alpha_flags != RENDER_ALPHA_VTX:
                    mat_alpha = nodes.new('ShaderNodeValue')
                    mat_alpha.outputs[0].default_value = material.alpha
                    mix = nodes.new('ShaderNodeMath')
                    mix.operation = 'MULTIPLY'
                    links.new(alpha.outputs[0], mix.inputs[0])
                    links.new(mat_alpha.outputs[0], mix.inputs[1])
                    alpha = mix
                    self.logger.debug('  base alpha: RENDER_DIFFUSE=0, alpha=%s → vtx_alpha * mat alpha %.3f',
                        alpha_names.get(alpha_flags, hex(alpha_flags)), material.alpha)
                else:
                    self.logger.debug('  base alpha: RENDER_DIFFUSE=0, alpha=VTX → vtx_alpha attribute only')


        last_color = color.outputs[0]
        last_alpha = alpha.outputs[0]
        bump_map  = None

        self.logger.debug('  textures enabled: %d', len(textures))
        for tex_i, texture in enumerate(textures):
            lightmap_type = texture.flags & TEX_LIGHTMAP_MASK
            passes_check = bool(lightmap_type & (TEX_LIGHTMAP_DIFFUSE | TEX_LIGHTMAP_AMBIENT | TEX_LIGHTMAP_SPECULAR | TEX_LIGHTMAP_EXT))
            colormap = texture.flags & TEX_COLORMAP_MASK
            self.logger.debug('  tex[%d] flags=0x%08X  lightmap=0x%X  passes=%s  colormap=0x%X  bump=%s',
                tex_i, texture.flags, lightmap_type, passes_check, colormap >> 16, bool(texture.flags & TEX_BUMP))
            if (texture.flags & TEX_COORD_MASK) == TEX_COORD_UV:
                uv = nodes.new('ShaderNodeUVMap')
                uv.uv_map = 'uvtex_' + str(texture.source - 4)
                uv_output = uv.outputs[0]
                self.logger.debug('  tex[%d] uv_map: "%s" (source=%d, coord=UV)',
                    tex_i, uv.uv_map, texture.source)
            elif (texture.flags & TEX_COORD_MASK) == TEX_COORD_REFLECTION:
                uv = nodes.new('ShaderNodeTexCoord')
                uv_output = uv.outputs[6]
                self.logger.debug('  tex[%d] uv_map: REFLECTION (source=%d)', tex_i, texture.source)
            else:
                uv_output = None
                self.logger.debug('  tex[%d] uv_map: NONE (coord_mask=0x%X, source=%d)',
                    tex_i, texture.flags & TEX_COORD_MASK, texture.source)

            mapping = nodes.new('ShaderNodeMapping')
            mapping.vector_type = 'TEXTURE'
            mapping.inputs[2].default_value = texture.rotation

            # Scale and translation match the reference exactly
            mapping.inputs[1].default_value = texture.translation
            mapping.inputs[3].default_value = texture.scale

            # Blender UV origin is bottom-left; GX is top-left — flip V
            mapping.inputs[1].default_value[1] = 1 - texture.scale[1] - texture.translation[1]

            #TODO: Is this correct?
            if (texture.flags & TEX_COORD_MASK) == TEX_COORD_REFLECTION:
                mapping.inputs[2].default_value[0] -= math.pi/2

            blender_texture = nodes.new('ShaderNodeTexImage')
            blender_texture.image = texture.image_data
            blender_texture.name = ("0x%X" % texture.id)
            self.logger.debug('  tex[%d] → image: %s', tex_i,
                texture.image_data.name if texture.image_data else 'None')

            self.logger.debug('  tex[%d] wrap_s=%d wrap_t=%d repeat_s=%d repeat_t=%d scale=%s trans=%s',
                tex_i, texture.wrap_s, texture.wrap_t, texture.repeat_s, texture.repeat_t,
                list(texture.scale), list(texture.translation))

            has_repeat = texture.wrap_s == GX_REPEAT or texture.wrap_t == GX_REPEAT
            has_mirror = texture.wrap_s == GX_MIRROR or texture.wrap_t == GX_MIRROR

            if has_repeat or has_mirror:
                blender_texture.extension = 'REPEAT'
            else:
                # GX CLAMP shows the edge pixel for out-of-range UVs — use EXTEND, not CLIP
                blender_texture.extension = 'EXTEND'

            if texture.lod:
                blender_texture.interpolation = self.interpolation_name_by_gx_constant[texture.lod.min_filter]

            # Apply repeat by pre-multiplying UVs before the mapping node.
            # This keeps the mapping's scale/translation identical to the reference
            # while adding the GX hardware's repeat-based UV scaling separately.
            if uv_output and (texture.repeat_s > 1 or texture.repeat_t > 1):
                multiply = nodes.new('ShaderNodeVectorMath')
                multiply.operation = 'MULTIPLY'
                multiply.inputs[1].default_value = (
                    texture.repeat_s if texture.repeat_s > 1 else 1,
                    texture.repeat_t if texture.repeat_t > 1 else 1,
                    1)
                links.new(uv_output, multiply.inputs[0])
                links.new(multiply.outputs[0], mapping.inputs[0])
            elif uv_output:
                links.new(uv_output, mapping.inputs[0])

            # TODO: Per-axis wrap handling is disabled because the Y translation
            # formula can shift texture coordinates outside [0,1], and clamping
            # in the transformed space clips the texture incorrectly.
            links.new(mapping.outputs[0], blender_texture.inputs[0])

            cur_color = blender_texture.outputs[0]
            cur_alpha = blender_texture.outputs[1]
            
            if texture.tev:
                tev = texture.tev
                if tev.active & TOBJ_TEVREG_ACTIVE_COLOR_TEV:
                    inputs = [self.make_tev_input(nodes, blender_texture, tev, i, True) for i in range(4)]
                    cur_color = self.make_tev_op(nodes, links, inputs, tev, True)

                if tev.active & TOBJ_TEVREG_ACTIVE_ALPHA_TEV:
                    inputs = [self.make_tev_input(nodes, blender_texture, tev, i, False) for i in range(4)]
                    cur_alpha = self.make_tev_op(nodes, links, inputs, tev, False)

                blender_texture.name += ' tev'
            if texture.flags & TEX_BUMP:
                # Bump map
                if bump_map:
                    # idk, just do blending for now to keep the nodes around
                    mix = nodes.new('ShaderNodeMixRGB')
                    mix.blend_type = 'MIX'
                    mix.inputs[0].default_value = texture.blending
                    links.new(bump_map, mix.inputs[1])
                    links.new(cur_color, mix.inputs[2])
                    bump_map = mix.outputs[0]
                else:
                    bump_map = cur_color
            else:
                # Color and alpha — apply for textures with a diffuse/ambient/specular/ext lightmap type,
                # or textures with no lightmap type set at all (treat as diffuse by default)
                lightmap_type = texture.flags & TEX_LIGHTMAP_MASK
                if lightmap_type == 0 or lightmap_type & (TEX_LIGHTMAP_DIFFUSE | TEX_LIGHTMAP_AMBIENT | TEX_LIGHTMAP_SPECULAR | TEX_LIGHTMAP_EXT):
                    if texture.flags & TEX_LIGHTMAP_SPECULAR and not self.render_mode & RENDER_SPECULAR:
                        continue

                    colormap = texture.flags & TEX_COLORMAP_MASK
                    if not (colormap == TEX_COLORMAP_NONE or colormap == TEX_COLORMAP_PASS):
                        mix = nodes.new('ShaderNodeMixRGB')
                        mix.blend_type = self.blender_colormap_ops_by_hsd_op[colormap]
                        mix.inputs[0].default_value = 1

                        mix.name = self.blender_colormap_names_by_hsd_op[colormap] + ' ' + str(texture.blending)

                        if not colormap == TEX_COLORMAP_REPLACE:
                            links.new(last_color, mix.inputs[1])
                            links.new(cur_color, mix.inputs[2])
                        if colormap == TEX_COLORMAP_ALPHA_MASK:
                            links.new(cur_alpha, mix.inputs[0])
                        elif colormap == TEX_COLORMAP_RGB_MASK:
                            links.new(cur_color, mix.inputs[0])
                        elif colormap == TEX_COLORMAP_BLEND:
                            mix.inputs[0].default_value = texture.blending
                        elif colormap == TEX_COLORMAP_REPLACE:
                            links.new(cur_color, mix.inputs[1])
                            mix.inputs[0].default_value = 0.0

                        last_color = mix.outputs[0]

                    # Alpha
                    alphamap = texture.flags & TEX_ALPHAMAP_MASK
                    if not (alphamap == TEX_ALPHAMAP_NONE or
                            alphamap == TEX_ALPHAMAP_PASS):
                        mix = nodes.new('ShaderNodeMixRGB')
                        mix.blend_type = self.blender_alphamap_ops_by_hsd_op[alphamap]
                        mix.inputs[0].default_value = 1

                        mix.name = self.blender_alphamap_names_by_hsd_op[alphamap]

                        if not alphamap == TEX_ALPHAMAP_REPLACE:
                            links.new(last_alpha, mix.inputs[1])
                            links.new(cur_alpha, mix.inputs[2])
                        if alphamap == TEX_ALPHAMAP_ALPHA_MASK:
                            links.new(cur_alpha, mix.inputs[0])
                        elif alphamap == TEX_ALPHAMAP_BLEND:
                            mix.inputs[0].default_value = texture.blending
                        elif alphamap == TEX_ALPHAMAP_REPLACE:
                            links.new(cur_alpha, mix.inputs[1])

                        last_alpha = mix.outputs[0]

        # Post-texture vertex color/alpha multiplication
        # Only when RENDER_DIFFUSE is set — vertex colors modulate the accumulated color.
        # When RENDER_DIFFUSE is not set, vertex color was already used as the base.
        if self.render_mode & RENDER_DIFFUSE:
            if diffuse_flags & RENDER_DIFFUSE_VTX:
                vtx_color = nodes.new('ShaderNodeAttribute')
                vtx_color.attribute_name = 'color_0'
                mult = nodes.new('ShaderNodeMixRGB')
                mult.inputs[0].default_value = 1
                mult.blend_type = 'MULTIPLY'
                links.new(vtx_color.outputs[0], mult.inputs[1])
                links.new(last_color, mult.inputs[2])
                last_color = mult.outputs[0]
                self.logger.debug('  post-tex: multiply by vtx color_0')

            if alpha_flags & RENDER_ALPHA_VTX:
                vtx_alpha = nodes.new('ShaderNodeAttribute')
                vtx_alpha.attribute_name = 'alpha_0'
                mult = nodes.new('ShaderNodeMixRGB')
                mult.inputs[0].default_value = 1
                mult.blend_type = 'MULTIPLY'
                links.new(vtx_alpha.outputs[0], mult.inputs[1])
                links.new(last_alpha, mult.inputs[2])
                last_alpha = mult.outputs[0]
                self.logger.debug('  post-tex: multiply by vtx alpha_0')
        else:
            self.logger.debug('  post-tex: skipped (RENDER_DIFFUSE not set)')

        # Final render settings. On the GameCube these would control how the rendered data is written to the EFB (Embedded Frame Buffer)

        alt_blend_mode = 'NOTHING'

        transparent_shader = False
        if self.pixel_engine_data:
            pixel_engine_data = self.pixel_engine_data
            self.logger.debug('  PE: type=%d src=%d dst=%d logic=%d z_comp=%d alpha_comp0=%d alpha_op=%d alpha_comp1=%d',
                pixel_engine_data.type, pixel_engine_data.source_factor,
                pixel_engine_data.destination_factor, pixel_engine_data.logic_op,
                pixel_engine_data.z_comp, pixel_engine_data.alpha_component_0,
                pixel_engine_data.alpha_op, pixel_engine_data.alpha_component_1)
            # PE (Pixel Engine) parameters can be given manually in this struct
            # TODO: implement other custom PE stuff
            # Blend mode
            # HSD_StateSetBlendMode    ((GXBlendMode) pe->type,
            #         (GXBlendFactor) pixel_engine_data->source_factor,
            #         (GXBlendFactor) pixel_engine_data->destination_factor,
            #         (GXLogicOp) pixel_engine_data->logic_op);
            if pixel_engine_data.type == GX_BM_NONE:
                pass #source data just overwrites EFB data (Opaque)

            elif pixel_engine_data.type == GX_BM_BLEND:
                # dst_pix_clr = src_pix_clr * source_factor + dst_pix_clr * destination_factor
                if pixel_engine_data.destination_factor == GX_BL_ZERO:
                    # Destination is completely overwritten
                    if pixel_engine_data.source_factor == GX_BL_ONE:
                        pass # Same as GX_BM_NONE

                    elif pixel_engine_data.source_factor == GX_BL_ZERO:
                        # Destination is set to 0
                        black = nodes.new('ShaderNodeRGB')
                        black.outputs[0].default_value[:] = [0,0,0,1]
                        last_color = black.outputs[0]

                    elif pixel_engine_data.source_factor == GX_BL_DSTCLR:
                        # Multiply source and destination
                        # blender_material.blend_method = 'MULTIPLY'
                        alt_blend_mode = 'MULTIPLY'

                    elif pixel_engine_data.source_factor == GX_BL_SRCALPHA:
                        # Blend with black by alpha
                        blend = nodes.new('ShaderNodeMixRGB')
                        links.new(last_alpha, blend.inputs[0])
                        blend.inputs[1].default_value = [0,0,0,0xFF]
                        links.new(last_color, blend.inputs[2])
                        last_color = blend.outputs[0]

                    elif pixel_engine_data.source_factor == GX_BL_INVSRCALPHA:
                        # Same as above with inverted alpha
                        blend = nodes.new('ShaderNodeMixRGB')
                        links.new(last_alpha, blend.inputs[0])
                        blend.inputs[2].default_value = [0,0,0,0xFF]
                        links.new(last_color, blend.inputs[1])
                        last_color = blend.outputs[0]

                    else:
                        # Can't be properly approximated with Eevee or Cycles
                        pass

                elif pixel_engine_data.destination_factor == GX_BL_ONE:
                    if pixel_engine_data.source_factor == GX_BL_ONE:
                        # Add source and destination
                        # blender_material.blend_method = 'ADD'
                        alt_blend_mode = 'ADD'

                    elif pixel_engine_data.source_factor == GX_BL_ZERO:
                        # Material is invisible
                        transparent_shader = True
                        blender_material.blend_method = 'HASHED'
                        invisible = nodes.new('ShaderNodeValue')
                        invisible.outputs[0].default_value = 0
                        last_alpha = invisible.outputs[0]

                    elif pixel_engine_data.source_factor == GX_BL_SRCALPHA:
                        # Add alpha blended color
                        transparent_shader = True
                        # blender_material.blend_method = 'ADD'
                        alt_blend_mode = 'ADD'
                        # Manually blend color
                        blend = nodes.new('ShaderNodeMixRGB')
                        links.new(last_alpha, blend.inputs[0])
                        blend.inputs[1].default_value = [0,0,0,0xFF]
                        links.new(last_color, blend.inputs[2])
                        last_color = blend.outputs[0]

                    elif pixel_engine_data.source_factor == GX_BL_INVSRCALPHA:
                        # Add inverse alpha blended color
                        transparent_shader = True
                        # blender_material.blend_method = 'ADD'
                        alt_blend_mode = 'ADD'
                        # Manually blend color
                        blend = nodes.new('ShaderNodeMixRGB')
                        links.new(last_alpha, blend.inputs[0])
                        blend.inputs[2].default_value = [0,0,0,0xFF]
                        links.new(last_color, blend.inputs[1])
                        last_color = blend.outputs[0]

                    else:
                        # Can't be properly approximated with Eevee or Cycles
                        pass

                elif (pixel_engine_data.destination_factor == GX_BL_INVSRCALPHA and pixel_engine_data.source_factor == GX_BL_SRCALPHA):
                    # Alpha Blend
                    transparent_shader = True
                    blender_material.blend_method = 'HASHED'

                elif (pixel_engine_data.destination_factor == GX_BL_SRCALPHA and pixel_engine_data.source_factor == GX_BL_INVSRCALPHA):
                    #Inverse Alpha Blend
                    transparent_shader = True
                    blender_material.blend_method = 'HASHED'
                    factor = nodes.new('ShaderNodeMath')
                    factor.operation = 'SUBTRACT'
                    factor.inputs[0].default_value = 1
                    factor.use_clamp = True
                    links.new(last_alpha, factor.inputs[1])
                    last_alpha = factor.outputs[0]

                else:
                    # Can't be properly approximated with Eevee or Cycles
                    pass

            elif pixel_engine_data.type == GX_BM_LOGIC:
                if pixel_engine_data.logic_op == GX_LO_CLEAR:
                    # Destination is set to 0
                    black = nodes.new('ShaderNodeRGB')
                    black.outputs[0].default_value[:] = [0,0,0,1]
                    last_color = black.outputs[0]

                elif pixel_engine_data.logic_op == GX_LO_SET:
                    # Destination is set to 1
                    white = nodes.new('ShaderNodeRGB')
                    white.outputs[0].default_value[:] = [1,1,1,1]
                    last_color = white.outputs[0]

                elif pixel_engine_data.logic_op == GX_LO_COPY:
                    pass # same as GX_BM_NONE ?

                elif pixel_engine_data.logic_op == GX_LO_INVCOPY:
                    # Invert color ?
                    invert = nodes.new('ShaderNodeInvert')
                    links.new(last_color, invert.inputs[1])
                    last_color = invert.outputs[0]

                elif pixel_engine_data.logic_op == GX_LO_NOOP:
                    # Material is invisible
                    transparent_shader = True
                    blender_material.blend_method = 'HASHED'
                    invisible = nodes.new('ShaderNodeValue')
                    invisible.outputs[0].default_value = 0
                    last_alpha = invisible.outputs[0]

                else:
                    # Can't be properly approximated with Eevee or Cycles
                    pass

            elif pixel_engine_data.type == GX_BM_SUBTRACT:
                pass #not doable right now

            else:
                raise PixelEngineUnknownBlendModeError(pixel_engine_data.type)
        else:
            # TODO: use the presets from the rendermode flags
            if self.render_mode & RENDER_XLU:
                transparent_shader = True
                blender_material.blend_method = 'BLEND'

        # Output shader
        shader = nodes.new('ShaderNodeBsdfPrincipled')
        # Specular
        if self.render_mode & RENDER_SPECULAR:
            shader.inputs['Specular'].default_value = self.material.shininess / 50
        else:
            shader.inputs['Specular'].default_value = 0
        # Specular tint
        shader.inputs['Specular Tint'].default_value = .5
        # Roughness
        shader.inputs['Roughness'].default_value = .5

        # Diffuse color
        if self.render_mode & RENDER_DIFFUSE:
            links.new(last_color, shader.inputs['Base Color'])
            # Alpha
            if transparent_shader:
                links.new(last_alpha, shader.inputs['Alpha'])
        else:
            # No diffuse lighting — use emission shader for flat/unlit appearance
            shader.inputs['Base Color'].default_value = [0, 0, 0, 1]
            emission = nodes.new('ShaderNodeEmission')
            links.new(last_color, emission.inputs['Color'])
            diffuse = emission
            # Alpha
            if transparent_shader:
                mixshader = nodes.new('ShaderNodeMixShader')
                transparent_sh = nodes.new('ShaderNodeBsdfTransparent')
                links.new(last_alpha, mixshader.inputs[0])
                links.new(transparent_sh.outputs[0], mixshader.inputs[1])
                links.new(diffuse.outputs[0], mixshader.inputs[2])
                diffuse = mixshader

            addshader = nodes.new('ShaderNodeAddShader')
            links.new(diffuse.outputs[0], addshader.inputs[0])
            links.new(shader.outputs[0], addshader.inputs[1])
            shader = addshader

        # Normal
        if bump_map:
            bump = nodes.new('ShaderNodeBump')
            bump.inputs[1].default_value = 1
            links.new(bump_map, bump.inputs[2])
            links.new(bump.outputs[0], shader.inputs['Normal'])

        # Add Additive or multiplicative alpha blending, since these don't have explicit options in 2.81 anymore
        if (alt_blend_mode == 'ADD'):
            blender_material.blend_method = 'BLEND'
            # Using emissive shader, unfortunately this will obviously override all the principled settings
            e = nodes.new('ShaderNodeEmission')
            # Is this really right ? comes from blender release notes
            e.inputs[1].default_value = 1.9
            t = nodes.new('ShaderNodeBsdfTransparent')
            add = nodes.new('ShaderNodeAddShader')
            links.new(last_color, e.inputs[0])
            links.new(e.outputs[0], add.inputs[0])
            links.new(t.outputs[0], add.inputs[1])
            shader = add

        elif (alt_blend_mode == 'MULTIPLY'):
            blender_material.blend_method = 'BLEND'
            # Using transparent shader, unfortunately this will obviously override all the principled settings
            t = nodes.new('ShaderNodeBsdfTransparent')
            links.new(last_color, t.inputs[0])
            shader = t

        # Output to Material
        links.new(shader.outputs[0], output.inputs[0])

        self.logger.debug('  final: transparent=%s, blend_method=%s, alt_blend=%s, '
            'PE=%s, joint_flags=0x%X',
            transparent_shader, blender_material.blend_method, alt_blend_mode,
            str(pixel_engine_data.type) if self.pixel_engine_data else 'None', joint_flags)

        output.name = 'Rendermode : 0x%X' % self.render_mode
        output.name += ' Transparent: ' + ('True' if transparent_shader else 'False')
        output.name += ' PixelEngine: ' + (str(pixel_engine_data.type) if self.pixel_engine_data else 'False')
        if self.pixel_engine_data and self.pixel_engine_data.type == GX_BM_BLEND:
            output.name += ' ' + str(pixel_engine_data.source_factor) + ' ' + str(pixel_engine_data.destination_factor)

        return blender_material

    # --- TEV (Texture Environment) methods ---
    # These implement the GameCube TEV pipeline as Blender shader nodes.
    # TODO: make_tev_op_comp is incomplete (stubbed to return inputs[0]).

    def make_tev_input(self, nodes, texture, tev, input, iscolor):
        if iscolor:
            flag = (tev.color_a, tev.color_b, tev.color_c, tev.color_d)[input]
            if not (flag == gx.GX_CC_TEXC or flag == gx.GX_CC_TEXA):
                color = nodes.new('ShaderNodeRGB')
            if flag == gx.GX_CC_ZERO:
                color.outputs[0].default_value = [0.0, 0.0, 0.0, 1]
            elif flag == gx.GX_CC_ONE:
                color.outputs[0].default_value = [1.0, 1.0, 1.0, 1]
            elif flag == gx.GX_CC_HALF:
                color.outputs[0].default_value = [0.5, 0.5, 0.5, 1]
            elif flag == gx.GX_CC_TEXC:
                return texture.outputs[0]
            elif flag == gx.GX_CC_TEXA:
                return texture.outputs[1]
            elif flag == hsd.TOBJ_TEV_CC_KONST_RGB:
                color.outputs[0].default_value = [tev.konst.red, tev.konst.green,tev.konst.blue,tev.konst.alpha]
            elif flag == hsd.TOBJ_TEV_CC_KONST_RRR:
                color.outputs[0].default_value = [tev.konst.red, tev.konst.red,tev.konst.red,tev.konst.alpha]
            elif flag == hsd.TOBJ_TEV_CC_KONST_GGG:
                color.outputs[0].default_value = [tev.konst.green, tev.konst.green,tev.konst.green,tev.konst.alpha]
            elif flag == hsd.TOBJ_TEV_CC_KONST_BBB:
                color.outputs[0].default_value = [tev.konst.blue, tev.konst.blue,tev.konst.blue,tev.konst.alpha]
            elif flag == hsd.TOBJ_TEV_CC_KONST_AAA:
                color.outputs[0].default_value = [tev.konst.alpha, tev.konst.alpha,tev.konst.alpha,tev.konst.alpha]
            elif flag == hsd.TOBJ_TEV_CC_TEX0_RGB:
                color.outputs[0].default_value = [tev.tev0.red, tev.tev0.green,tev.tev0.blue,tev.tev0.alpha]
            elif flag == hsd.TOBJ_TEV_CC_TEX0_AAA:
                color.outputs[0].default_value = [tev.tev0.alpha, tev.tev0.alpha,tev.tev0.alpha,tev.tev0.alpha]
            elif flag == hsd.TOBJ_TEV_CC_TEX1_RGB:
                color.outputs[0].default_value = [tev.tev1.red, tev.tev1.green,tev.tev1.blue,tev.tev1.alpha]
            elif flag == hsd.TOBJ_TEV_CC_TEX1_AAA:
                color.outputs[0].default_value = [tev.tev1.alpha, tev.tev1.alpha,tev.tev1.alpha,tev.tev1.alpha]
            else:
                self.logger.warning("Unknown tev color input: 0x%X", flag)
                return texture.outputs[0]
            return color.outputs[0]
        else:
            flag = (tev.alpha_a, tev.alpha_b, tev.alpha_c, tev.alpha_d)[input]
            if not (flag == gx.GX_CA_TEXA):
                alpha = nodes.new('ShaderNodeValue')
            if flag == gx.GX_CA_ZERO:
                alpha.outputs[0].default_value = 0.0
            elif flag == gx.GX_CA_TEXA:
                return texture.outputs[1]
            elif flag == hsd.TOBJ_TEV_CA_KONST_R:
                alpha.outputs[0].default_value = self.normcolor((tev.konst[0], 'R'))
            elif flag == hsd.TOBJ_TEV_CA_KONST_G:
                alpha.outputs[0].default_value = self.normcolor((tev.konst[1], 'G'))
            elif flag == hsd.TOBJ_TEV_CA_KONST_B:
                alpha.outputs[0].default_value = self.normcolor((tev.konst[2], 'B'))
            elif flag == hsd.TOBJ_TEV_CA_KONST_A:
                alpha.outputs[0].default_value = self.normcolor((tev.konst[3], 'A'))
            elif flag == hsd.TOBJ_TEV_CA_TEX0_A:
                alpha.outputs[0].default_value = self.normcolor((tev.tev0[3], 'A'))
            elif flag == hsd.TOBJ_TEV_CA_TEX1_A:
                alpha.outputs[0].default_value = self.normcolor((tev.tev1[3], 'A'))
            else:
                self.logger.warning("Unknown tev alpha input: 0x%X", flag)
                return texture.outputs[1]
            return alpha.outputs[0]

    def make_tev_op(self, nodes, links, inputs, tev, iscolor):
        scale_dict = {
            gx.GX_CS_SCALE_1: 1,
            gx.GX_CS_SCALE_2: 2,
            gx.GX_CS_SCALE_4: 4,
            gx.GX_CS_DIVIDE_2: 0.5,
        }
        if iscolor:
            if tev.color_op == gx.GX_TEV_ADD or tev.color_op == gx.GX_TEV_SUB:
                last_node = self.make_tev_op_add_sub(nodes, links, inputs, tev, iscolor)
                if not tev.color_bias == gx.GX_TB_ZERO:
                    bias = nodes.new('ShaderNodeMixRGB')
                    bias.inputs[0].default_value = 1
                    if tev.color_bias == gx.GX_TB_ADDHALF:
                        bias.blend_type = 'ADD'
                    else:
                        bias.blend_type = 'SUBTRACT'
                    links.new(last_node, bias.inputs[1])
                    bias.inputs[2].default_value = [0.5, 0.5, 0.5, 1]
                    last_node = bias.outputs[0]

                scale = nodes.new('ShaderNodeMixRGB')
                scale.blend_type = 'MULTIPLY'
                scale.inputs[0].default_value = 1
                if tev.color_clamp == gx.GX_TRUE:
                    scale.use_clamp = True
                links.new(last_node, scale.inputs[1])
                scale.inputs[2].default_value = [scale_dict[tev.color_scale]] * 4
                last_node = scale.outputs[0]
            else:
                last_node = self.make_tev_op_comp(nodes, links, inputs, tev, iscolor)
                if tev.color_clamp == gx.GX_TRUE:
                    scale = nodes.new('ShaderNodeMixRGB')
                    scale.blend_type = 'MULTIPLY'
                    scale.inputs[0].default_value = 1
                    scale.use_clamp = True
                    links.new(last_node, scale.inputs[1])
                    scale.inputs[2].default_value = [scale_dict[tev.color_scale]] * 4
                    last_node = scale.outputs[0]
        else:
            if tev.alpha_op == gx.GX_TEV_ADD or tev.alpha_op == gx.GX_TEV_SUB:
                last_node = self.make_tev_op_add_sub(nodes, links, inputs, tev, iscolor)
                if not tev.alpha_bias == gx.GX_TB_ZERO:
                    bias = nodes.new('ShaderNodeMath')
                    bias.operation = 'ADD'
                    links.new(last_node, bias.inputs[0])
                    if tev.alpha_bias == gx.GX_TB_ADDHALF:
                        bias.inputs[1].default_value = 0.5
                    else:
                        bias.inputs[1].default_value = -0.5
                    last_node = bias.outputs[0]

                scale = nodes.new('ShaderNodeMath')
                scale.operation = 'MULTIPLY'
                if tev.alpha_clamp == gx.GX_TRUE:
                    scale.use_clamp = True
                links.new(last_node, scale.inputs[0])
                scale.inputs[1].default_value = scale_dict[tev.alpha_scale]
                last_node = scale.outputs[0]
            else:
                last_node = self.make_tev_op_comp(nodes, links, inputs, tev, iscolor)
                if tev.alpha_clamp == gx.GX_TRUE:
                    scale = nodes.new('ShaderNodeMath')
                    scale.operation = 'MULTIPLY'
                    scale.use_clamp = True
                    links.new(last_node, scale.inputs[0])
                    scale.inputs[1].default_value = 1
                    last_node = scale.outputs[0]
        return last_node

    def make_tev_op_add_sub(self, nodes, links, inputs, tev, iscolor):
        if iscolor:
            sub0 = nodes.new('ShaderNodeMixRGB')
            sub0.inputs[0].default_value = 1
            sub0.blend_type = 'SUBTRACT'
            sub0.inputs[1].default_value = [1,1,1,1]
            links.new(inputs[2], sub0.inputs[2])

            mul0 = nodes.new('ShaderNodeMixRGB')
            mul0.inputs[0].default_value = 1
            mul0.blend_type = 'MULTIPLY'
            links.new(inputs[1], mul0.inputs[1])
            links.new(inputs[2], mul0.inputs[2])

            mul1 = nodes.new('ShaderNodeMixRGB')
            mul1.inputs[0].default_value = 1
            mul1.blend_type = 'MULTIPLY'
            links.new(inputs[0], mul1.inputs[1])
            links.new(sub0.outputs[0], mul1.inputs[2])

            add0 = nodes.new('ShaderNodeMixRGB')
            add0.inputs[0].default_value = 1
            add0.blend_type = 'ADD'
            links.new(mul1.outputs[0], add0.inputs[1])
            links.new(mul0.outputs[0], add0.inputs[2])

            if tev.color_op == gx.GX_TEV_ADD:
                add1 = nodes.new('ShaderNodeMixRGB')
                add1.inputs[0].default_value = 1
                add1.blend_type = 'ADD'
                links.new(inputs[3], add1.inputs[1])
                links.new(add0.outputs[0], add1.inputs[2])
                return add1.outputs[0]
            else:
                sub1 = nodes.new('ShaderNodeMixRGB')
                sub1.inputs[0].default_value = 1
                sub1.blend_type = 'SUBTRACT'
                links.new(inputs[3], sub1.inputs[1])
                links.new(add0.outputs[0], sub1.inputs[2])
                return sub1.outputs[0]
        else:
            sub0 = nodes.new('ShaderNodeMath')
            sub0.operation = 'SUBTRACT'
            sub0.inputs[1].default_value = 1.0
            links.new(inputs[2], sub0.inputs[2])

            mul0 = nodes.new('ShaderNodeMath')
            mul0.operation = 'MULTIPLY'
            links.new(inputs[1], mul0.inputs[1])
            links.new(inputs[2], mul0.inputs[2])

            mul1 = nodes.new('ShaderNodeMath')
            mul1.operation = 'MULTIPLY'
            links.new(inputs[0], mul1.inputs[1])
            links.new(sub0.outputs[0], mul1.inputs[2])

            add0 = nodes.new('ShaderNodeMath')
            add0.operation = 'ADD'
            links.new(mul1.outputs[0], add0.inputs[1])
            links.new(mul0.outputs[0], add0.inputs[2])

            if tev.alpha_op == gx.GX_TEV_ADD:
                add1 = nodes.new('ShaderNodeMath')
                add1.operation = 'ADD'
                links.new(inputs[3], add1.inputs[1])
                links.new(add0.outputs[0], add1.inputs[2])
                return add1.outputs[0]
            else:
                sub1 = nodes.new('ShaderNodeMath')
                sub1.operation = 'SUBTRACT'
                links.new(inputs[3], sub1.inputs[1])
                links.new(add0.outputs[0], sub1.inputs[2])
                return sub1.outputs[0]

    def make_tev_op_comp(self, nodes, links, inputs, tev, iscolor):
        # TODO: Implement TEV comparison operations
        return inputs[0]

    def _make_per_axis_wrap(self, nodes, links, uv_input, wrap_s, wrap_t):
        """Insert UV processing nodes for per-axis wrap mode handling.

        When the texture node is set to REPEAT (because at least one axis repeats)
        but the other axis should clamp, we clamp that axis's UV coordinate to [0,1]
        so it doesn't tile.
        """
        separate = nodes.new('ShaderNodeSeparateXYZ')
        separate.name = 'wrap_separate'
        links.new(uv_input, separate.inputs[0])

        s_out = separate.outputs[0]
        t_out = separate.outputs[1]

        if wrap_s == GX_CLAMP:
            clamp_s = nodes.new('ShaderNodeClamp')
            clamp_s.name = 'clamp_S'
            clamp_s.inputs[1].default_value = 0.0  # min
            clamp_s.inputs[2].default_value = 1.0  # max
            links.new(s_out, clamp_s.inputs[0])
            s_out = clamp_s.outputs[0]

        if wrap_t == GX_CLAMP:
            clamp_t = nodes.new('ShaderNodeClamp')
            clamp_t.name = 'clamp_T'
            clamp_t.inputs[1].default_value = 0.0
            clamp_t.inputs[2].default_value = 1.0
            links.new(t_out, clamp_t.inputs[0])
            t_out = clamp_t.outputs[0]

        combine = nodes.new('ShaderNodeCombineXYZ')
        combine.name = 'wrap_combine'
        links.new(s_out, combine.inputs[0])
        links.new(t_out, combine.inputs[1])
        links.new(separate.outputs[2], combine.inputs[2])

        return combine.outputs[0]

    @staticmethod
    def _srgb_to_linear(color):
        result = []
        for c in color[0:3]:
            if c <= 0.0404482362771082:
                result.append(c / 12.92)
            else:
                result.append(pow((c + 0.055) / 1.055, 2.4))
        if len(color) > 3:
            result.append(color[3])
        return tuple(result)

    @staticmethod
    def normcolor(x):
        """Normalize a u8 color value to float, with sRGB-to-linear conversion for RGB channels."""
        if len(x) > 2:
            color = [c / 255 for c in x]
            return MaterialObject._srgb_to_linear(color)
        else:
            channel_type = x[1]
            val = x[0] / 255
            if channel_type in ('R', 'G', 'B'):
                return MaterialObject._srgb_to_linear([val])[0]
            elif channel_type == 'A':
                return val

    interpolation_name_by_gx_constant = {
        GX_NEAR: 'Closest',
        GX_LINEAR: 'Linear',
        GX_NEAR_MIP_NEAR: 'Closest',
        GX_LIN_MIP_NEAR: 'Linear',
        GX_NEAR_MIP_LIN: 'Closest',
        GX_LIN_MIP_LIN: 'Cubic'
    }

    blender_colormap_ops_by_hsd_op = {
        TEX_COLORMAP_ALPHA_MASK : 'MIX',
        TEX_COLORMAP_RGB_MASK   : 'MIX',
        TEX_COLORMAP_BLEND      : 'MIX',
        TEX_COLORMAP_MODULATE   : 'MULTIPLY',
        TEX_COLORMAP_REPLACE    : 'ADD',
        TEX_COLORMAP_ADD        : 'ADD',
        TEX_COLORMAP_SUB        : 'SUBTRACT',
    }

    blender_colormap_names_by_hsd_op = {
        TEX_COLORMAP_NONE: 'TEX_COLORMAP_NONE',
        TEX_COLORMAP_PASS: 'TEX_COLORMAP_PASS',
        TEX_COLORMAP_REPLACE: 'TEX_COLORMAP_REPLACE',
        TEX_COLORMAP_ALPHA_MASK: 'TEX_COLORMAP_ALPHA_MASK',
        TEX_COLORMAP_RGB_MASK: 'TEX_COLORMAP_RGB_MASK',
        TEX_COLORMAP_BLEND: 'TEX_COLORMAP_BLEND',
        TEX_COLORMAP_ADD: 'TEX_COLORMAP_ADD',
        TEX_COLORMAP_SUB: 'TEX_COLORMAP_SUB',
        TEX_COLORMAP_MODULATE: 'TEX_COLORMAP_MODULATE'
    }

    blender_alphamap_ops_by_hsd_op = {
        TEX_ALPHAMAP_ALPHA_MASK : 'MIX',
        TEX_ALPHAMAP_BLEND      : 'MIX',
        TEX_ALPHAMAP_MODULATE   : 'MULTIPLY',
        TEX_ALPHAMAP_REPLACE    : 'ADD',
        TEX_ALPHAMAP_ADD        : 'ADD',
        TEX_ALPHAMAP_SUB        : 'SUBTRACT',
    }

    blender_alphamap_names_by_hsd_op = {
        TEX_ALPHAMAP_NONE: 'TEX_ALPHAMAP_NONE',
        TEX_ALPHAMAP_PASS: 'TEX_ALPHAMAP_PASS',
        TEX_ALPHAMAP_REPLACE: 'TEX_ALPHAMAP_REPLACE',
        TEX_ALPHAMAP_ALPHA_MASK: 'TEX_ALPHAMAP_ALPHA_MASK',
        TEX_ALPHAMAP_BLEND: 'TEX_ALPHAMAP_BLEND',
        TEX_ALPHAMAP_ADD: 'TEX_ALPHAMAP_ADD',
        TEX_ALPHAMAP_SUB: 'TEX_ALPHAMAP_SUB',
        TEX_ALPHAMAP_MODULATE: 'TEX_ALPHAMAP_MODULATE'
    }