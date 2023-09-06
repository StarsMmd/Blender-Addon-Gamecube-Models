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

    def build(self, builder):

        material = self.material
        blender_material = bpy.data.materials.new('')
        blender_material.use_nodes = True
        nodes = blender_material.node_tree.nodes
        links = blender_material.node_tree.links

        for node in nodes:
            nodes.remove(node)
        output = nodes.new('ShaderNodeOutputMaterial')

        material.diffuse.transform()
        diffuse_color = material.diffuse.asRGBAList()

        textures = []
        texture_number = 0
        texture = self.texture
        # Note: there shouldn't be more than 7 textures per material
        while texture:
            # Check if texture is enabled in the material
            if self.render_mode & (1 << (len(textures) + 4)):
                textures.append(texture)
            texture = texture.next

        alpha = None
        if self.render_mode & RENDER_DIFFUSE:
            color = nodes.new('ShaderNodeRGB')
            if (self.render_mode & RENDER_DIFFUSE_BITS) == RENDER_DIFFUSE_VTX:
                color.outputs[0].default_value[:] = [1,1,1,1]
            else:
                color.outputs[0].default_value[:] = diffuse_color

            alpha = nodes.new('ShaderNodeValue')
            if (self.render_mode & RENDER_ALPHA_BITS) == RENDER_ALPHA_VTX:
                alpha.outputs[0].default_value = 1
            else:
                alpha.outputs[0].default_value = material.alpha
        else:
            if (self.render_mode & CHANNEL_FIELD) == RENDER_DIFFUSE_MAT:
                color = nodes.new('ShaderNodeRGB')
                color.outputs[0].default_value[:] = mat_diffuse_color
            else:
                # Toon not supported. 
                # TODO: confirm if any models use Toon textures
                # if toon:
                #    color = nodes.new('ShaderNodeTexImage')
                #    color.image = toon.image_data
                #    #TODO: add the proper texture mapping
                # else:
                color = nodes.new('ShaderNodeAttribute')
                color.attribute_name = 'color_0'

                if not ((self.render_mode & RENDER_DIFFUSE_BITS) == RENDER_DIFFUSE_VTX):
                    diffuse = nodes.new('ShaderNodeRGB')
                    diffuse.outputs[0].default_value[:] = diffuse_color
                    mix = nodes.new('ShaderNodeMixRGB')
                    mix.blend_type = 'ADD'
                    mix.inputs[0].default_value = 1
                    links.new(color.outputs[0], mix.inputs[1])
                    links.new(diffuse.outputs[0], mix.inputs[2])
                    color = mix

            if (self.render_mode & RENDER_ALPHA_BITS) == RENDER_ALPHA_MAT:
                alpha = nodes.new('ShaderNodeValue')
                alpha.outputs[0].default_value = material.alpha
            else:
                alpha = nodes.new('ShaderNodeAttribute')
                alpha.attribute_name = 'alpha_0'

                if not (self.render_mode & RENDER_ALPHA_BITS) == RENDER_ALPHA_VTX:
                    material_alpha = nodes.new('ShaderNodeValue')
                    material_alpha.outputs[0].default_value = material.alpha
                    mix = nodes.new('ShaderNodeMath')
                    mix.operation = 'MULTIPLY'
                    links.new(alpha.outputs[0], mix.inputs[0])
                    links.new(material_alpha.outputs[0], mix.inputs[1])
                    alpha = mix


        last_color = color.outputs[0]
        last_alpha = alpha.outputs[0]
        bump_map  = None

        for texture in textures:
            if (texture.flags & TEX_COORD_MASK) == TEX_COORD_UV:
                uv = nodes.new('ShaderNodeUVMap')
                uv.uv_map = 'uvtex_' + str(texture.id)
                uv_output = uv.outputs[0]
            elif (texture.flags & TEX_COORD_MASK) == TEX_COORD_REFLECTION:
                uv = nodes.new('ShaderNodeTexCoord')
                uv_output = uv.outputs[6]
            else:
                uv_output = None

            mapping = nodes.new('ShaderNodeMapping')
            mapping.vector_type = 'TEXTURE'
            mapping.inputs[1].default_value = texture.translation 
            mapping.inputs[2].default_value = texture.rotation 
            mapping.inputs[3].default_value = texture.scale 

            # Blender UV coordinates are relative to the bottom left so we need to account for that
            mapping.inputs[1].default_value[1] = 1 - (texture.scale[1] * (texture.translation[1] + 1))

            #TODO: Is this correct?
            if (texture.flags & TEX_COORD_MASK) == TEX_COORD_REFLECTION:
                mapping.inputs[2].default_value[0] -= math.pi/2

            blender_texture = nodes.new('ShaderNodeTexImage')
            blender_texture.image = texture.image_data
            blender_texture.name = ("0x%X" % texture.id)
            blender_texture.name += ' flags: %X' % texture.flags
            blender_texture.name += (' image: 0x%X ' % (texture.image.id if texture.image else -1))
            blender_texture.name += (' tlut: 0x%X' % (texture.palette.id if texture.palette else -1))

            blender_texture.extension = 'EXTEND'
            if texture.wrap_t == GX_REPEAT:
                blender_texture.extension = 'REPEAT'

            if texture.lod:
                blender_texture.interpolation = self.interpolation_name_by_gx_constant[texture.lod.min_filter]

            if uv_output:
                links.new(uv_output, mapping.inputs[0])
            links.new(mapping.outputs[0], blender_texture.inputs[0])

            cur_color = blender_texture.outputs[0]
            cur_alpha = blender_texture.outputs[1]
            
            if texture.tev:
                tev = texture.tev
                if tev.active & TOBJ_TEVREG_ACTIVE_COLOR_TEV:
                    inputs = [make_tev_input(nodes, blender_texture, tev, i, True) for i in range(4)]
                    cur_color = make_tev_op(nodes, links, inputs, tev, True)

                if tev.active & TOBJ_TEVREG_ACTIVE_ALPHA_TEV:
                    inputs = [make_tev_input(nodes, blender_texture, tev, i, False) for i in range(4)]
                    cur_alpha = make_tev_op(nodes, links, inputs, tev, False)

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
                # Color
                if (texture.flags & TEX_LIGHTMAP_MASK) & (TEX_LIGHTMAP_DIFFUSE | TEX_LIGHTMAP_EXT):
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
                #do alpha
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

        # Final render settings. On the GameCube these would control how the rendered data is written to the EFB (Embedded Frame Buffer)

        alt_blend_mode = 'NOTHING'

        transparent_shader = False
        if self.pixel_engine_data:
            pixel_engine_data = self.pixel_engine_data
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

                    elif pixel_engine_data.source_factor == INVSRCALPHA:
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
                blender_material.blend_method = 'HASHED'

        # Output shader
        shader = nodes.new('ShaderNodeBsdfPrincipled')
        # Specular
        if self.render_mode & RENDER_SPECULAR:
            shader.inputs[5].default_value = self.material.shininess / 50
        else:
            shader.inputs[5].default_value = 0
        # Specular tint
        shader.inputs[6].default_value = .5
        # Roughness
        shader.inputs[7].default_value = .5

        # Diffuse color
        links.new(last_color, shader.inputs[0])

        # Alpha
        if transparent_shader:
            #
            #alpha_factor = nodes.new('ShaderNodeMath')
            #alpha_factor.operation = 'POWER'
            #alpha_factor.inputs[1].default_value = 3
            #links.new(last_alpha, alpha_factor.inputs[0])
            #last_alpha = alpha_factor.outputs[0]
            #
            links.new(last_alpha, shader.inputs[18])

        # Normal
        if bump_map:
            bump = nodes.new('ShaderNodeBump')
            bump.inputs[1].default_value = 1
            links.new(bump_map, bump.inputs[2])
            links.new(bump.outputs[0], shader.inputs[19])

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

        output.name = 'Rendermode : 0x%X' % self.render_mode
        output.name += ' Transparent: ' + ('True' if transparent_shader else 'False')
        output.name += ' PixelEngine: ' + (str(pixel_engine_data.type) if self.pixel_engine_data else 'False')
        if self.pixel_engine_data and self.pixel_engine_data.type == GX_BM_BLEND:
            output.name += ' ' + str(pixel_engine_data.source_factor) + ' ' + str(pixel_engine_data.destination_factor)

        return blender_material

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