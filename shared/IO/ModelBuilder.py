import bpy

from ..Nodes import *
from ..Errors import *

class ModelBuilder(object):

	def __init__(self, context, section, options):
		# Settings chosen for the parser
		# - "ik_hack"   : A boolean for whether or not to scale down bones so ik works correctly
		# - "max_frame" : An integer for the maximum number of frames to read from an animation, 0 for no limit
		# - "verbose"   : Prints more output for debugging purposes
		self.options = options

		self.context = context
		self.section = section

		self.models = []
		self.lights = []
		self.camera = None
		self.fog = None

		self.textures = {}
		self.materials = {}
		self.meshes = {}

		if self.section.root_node == None:
			return

		all_nodes = section.root_node.toList()

		texture_nodes = list(filter(lambda node: isinstance(node, Texture), all_nodes))
		for texture in texture_nodes:
			self.textures[texture.id] = texture.image_data

		material_nodes = list(filter(lambda node: isinstance(node, MaterialObject), all_nodes))
		for mobject in material_nodes:
			#TODO: uncomment once implementation is ready
			continue
			#self.materials[mobject.id] = self.approximateCyclesMaterial(mobject)

		mesh_nodes = list(filter(lambda node: isinstance(node, Mesh), all_nodes))
		for mesh in mesh_nodes:
			pobject = mesh.pobject
			while pobject:
				#TODO: uncomment once implementation is ready
				# blender_mesh = make_mesh(pobject)
				# # Add material
				# material = materials.get(mesh.mobject.id)
				# blender_mesh.data.materials.append(material)
				pobject = pobject.next
				# self.meshes[mesh.id] = blender_mesh

		if isinstance(self.section.root_node, Joint):
			model = ModelSet.fromRootJoint(self.section.root_node)
			self.models.append(model)

		elif isinstance(self.section.root_node, SceneData):
			scene_data = self.section.root_node

			self.camera = scene_data.camera
			self.fog = scene_data.fog
			self.lights = scene_data.lights
			self.models = scene_data.models

	def build(self):
		if self.options.get("verbose"):
			print("Building model from section:", self.section.section_name)

		for model in self.models:
			self.importModel(model)

		for light in self.lights:
			self.importModel(model)

		if self.camera != None:
			self.importCamera(self.camera)

		if self.fog != None:
			self.importFog(self.fog)


	# TODO: complete implementation
	def importModel(self, model):
		n_a = len(model.animated_joints) if model.animated_joints else 0
		n_m = len(model.animated_material_joints) if model.animated_material_joints else 0
		n_s = len(model.animated_shape_joints) if model.animated_shape_joints else 0

		anim_count = max(n_a, n_m, n_s)

		return

	def importLight(self, light):
		pass

	def importCamera(self, camera):
		pass

	def importFog(self, fog):
		pass

	# TODO: fix up implementation
	def make_mesh(self, pobj):
		name = ''
		if pobj.name:
			name = pobj.name

		displist = pobj.displist
		vtxdesclist = pobj.vtxdesclist
		displistsize = pobj.displistsize

		print('POBJ FLAGS: %.8X' % pobj.flags)

		i = 0 #index of the vtxdesc that holds vertex position data
		for vtxdesc in vtxdesclist:
		    if vtxdesc.attr == gx.GX_VA_POS:
		        break
		    i += 1
		if not i < len(vtxdesclist):
		    error_output("Mesh contains no position information")
		    return None
		#vertices, faces = read_geometry(vtxdesclist, displist, i)
		#TODO: move the loop here to avoid redundancy
		sources, facelists, normdicts = read_geometry(vtxdesclist, displist, displistsize)
		vertices = sources[i]
		faces = facelists[i]

		# Create mesh and object
		me = bpy.data.meshes.new(name + 'Mesh')
		ob = bpy.data.objects.new(name, me)
		ob.location = Vector((0,0,0))
		# Link object to scene
		bpy.context.scene.collection.objects.link(ob)

		# Create mesh from given verts, edges, faces. Either edges or
		# faces should be [], or you ask for problems

		me.from_pydata(vertices, [], faces)

		if pobj.u:
		    type = pobj.flags & hsd.POBJ_TYPE_MASK
		    if type == hsd.POBJ_SHAPEANIM:
		        shape_set = pobj.u
		        make_shapeset(ob, shape_set, normdicts[i])
		        make_rigid_skin(pobj)
		    elif type == hsd.POBJ_ENVELOPE:
		        envelope_list = pobj.u
		        envelope_vtxdesc_idx = -1
		        for vtxnum, vtxdesc in enumerate(vtxdesclist):
		            if vtxdesc.attr == gx.GX_VA_PNMTXIDX: #?
		                envelope_vtxdesc_idx = vtxnum
		        if not envelope_vtxdesc_idx < 0:
		            make_deform_skin(pobj, envelope_list, sources[envelope_vtxdesc_idx], facelists[envelope_vtxdesc_idx], faces)
		        else:
		            error_output('INVALID ENVELOPE: %.8X' % (pobj.id))

		    else:
		        #skin
		        #deprecated, probably still used somewhere though
		        joint = pobj.u
		        make_skin(pobj, joint)

		else:
		    make_rigid_skin(pobj)


		#me.calc_normals()
		print(me.name)
		#print_primitives(pobj.vtxdesclist, pobj.displist, pobj.displistsize)
		pobj.normals = None
		for vtxnum, vtxdesc in enumerate(vtxdesclist):
		    if vtxdesc_is_tex(vtxdesc):
		        uvlayer = make_texture_layer(me, vtxdesc, sources[vtxnum], facelists[vtxnum])
		    elif vtxdesc.attr == gx.GX_VA_NRM or vtxdesc.attr == gx.GX_VA_NBT:
		        assign_normals_to_mesh(pobj, me, vtxdesc, sources[vtxnum], facelists[vtxnum])
		        me.use_auto_smooth = True
		    elif (vtxdesc.attr == gx.GX_VA_CLR0 or
		          vtxdesc.attr == gx.GX_VA_CLR1):
		        add_color_layer(me, vtxdesc, sources[vtxnum], facelists[vtxnum])

		# Update mesh with new data
		me.update(calc_edges = True, calc_edges_loose = False)
		#remove degenerate faces (These mostly occur due to triangle strips creating invisible faces when changing orientation)

		print_primitives(pobj.vtxdesclist, pobj.displist, pobj.displistsize)

		return ob

	# TODO: fix up implementation
	def approximateCyclesMaterial(self, material_object):
	    material = material_object.material
	    mat = bpy.data.materials.new('')
	    mat.use_nodes = True
	    nodes = mat.node_tree.nodes
	    links = mat.node_tree.links
	    #diff = nodes['Diffuse BSDF']
	    #output = nodes['Material Output']
	    for node in nodes:
	        nodes.remove(node)
	    output = nodes.new('ShaderNodeOutputMaterial')
	    #nodes.remove(diff)

	    mat_diffuse_color = normcolor(material.diffuse)

	    #XXX: Print material flags etc
	    print(mat.name)
	    notice_output('MOBJ FLAGS:\nrendermode: %.8X' % mobj.rendermode)
	    if mobj.pedesc:
	        pedesc = mobj.pedesc
	        notice_output('PEDESC FLAGS:\nflags: %.2X\nref0: %.2X\nref1: %.2X\ndst_alpha: %.2X\ntype: %.2X\nsrc_factor: %.2X\ndst_factor: %.2X\nlogic_op: %.2X\nz_comp: %.2X\nalpha_comp0: %.2X\nalpha_op: %.2X\nalpha_comp1: %.2X' % \
	                       (pedesc.flags, pedesc.ref0, pedesc.ref1, pedesc.dst_alpha, pedesc.type, pedesc.src_factor, pedesc.dst_factor, pedesc.logic_op, pedesc.z_comp, pedesc.alpha_comp0, pedesc.alpha_op, pedesc.alpha_comp1))


	    textures = []
	    toon = None
	    tex_num = 0
	    texdesc = mobj.texdesc
	    while texdesc:
	        #if texdesc.flag & hsd.TEX_COORD_TOON:
	        #    toon = texdesc

	        #XXX:
	        notice_output('TOBJ FLAGS:\nid: %.8X\nsrc: %.8X\nflag: %.8X' % (texdesc.texid, texdesc.src, texdesc.flag))
	        if texdesc.tev:
	            tev = texdesc.tev
	            notice_output('TEV FLAGS:\ncolor_op: %.2X\nalpha_op: %.2X\ncolor_bias: %.2X\nalpha_bias: %.2X\n\
	color_scale: %.2X\nalpha_scale: %.2X\ncolor_clamp: %.2X\nalpha_clamp: %.2X\n\
	color_a: %.2X color_b: %.2X color_c: %.2X color_d: %.2X\n\
	alpha_a: %.2X alpha_b: %.2X alpha_c: %.2X alpha_d: %.2X\n\
	konst: %.2X%.2X%.2X%.2X tev0: %.2X%.2X%.2X%.2X tev1: %.2X%.2X%.2X%.2X\n\
	active: %.8X' % ((tev.color_op, tev.alpha_op, tev.color_bias, tev.alpha_bias,\
	                                            tev.color_scale, tev.alpha_scale, tev.color_clamp, tev.alpha_clamp, \
	                                            tev.color_a, tev.color_b, tev.color_c, tev.color_d, \
	                                            tev.alpha_a, tev.alpha_b, tev.alpha_c, tev.alpha_d) + \
	                                            tuple(tev.konst) + tuple(tev.tev0) + tuple(tev.tev1) + \
	                                            (tev.active,)))

	        print('%.8X' % texdesc.flag)
	        #if texdesc.flag & (hsd.TEX_LIGHTMAP_DIFFUSE | hsd.TEX_LIGHTMAP_AMBIENT):
	        if mobj.rendermode & (1 << (tex_num + 4)): #is this texture enabled in the material?
	            textures.append(texdesc)
	        texdesc = texdesc.next
	        tex_num += 1
	        if tex_num > 7:
	            break

	    print('textures: %d' % len(textures))

	    if mobj.rendermode & hsd.RENDER_DIFFUSE:
	        color = nodes.new('ShaderNodeRGB')
	        if (mobj.rendermode & hsd.RENDER_DIFFUSE_BITS) == hsd.RENDER_DIFFUSE_VTX:
	            color.outputs[0].default_value[:] = [1,1,1,1]
	        else:
	            color.outputs[0].default_value[:] = mat_diffuse_color

	        alpha = nodes.new('ShaderNodeValue')
	        if (mobj.rendermode & hsd.RENDER_ALPHA_BITS) == hsd.RENDER_ALPHA_VTX:
	            alpha.outputs[0].default_value = 1
	        else:
	            alpha.outputs[0].default_value = material.alpha
	    else:
	        if (mobj.rendermode & hsd.CHANNEL_FIELD) == hsd.RENDER_DIFFUSE_MAT:
	            color = nodes.new('ShaderNodeRGB')
	            color.outputs[0].default_value[:] = mat_diffuse_color
	        else:
	            #Toon not supported
	            #if toon:
	            #    color = nodes.new('ShaderNodeTexImage')
	            #    color.image = image_dict[toon.id]
	            #    #TODO: add the proper texture mapping
	            #else:
	            color = nodes.new('ShaderNodeAttribute')
	            color.attribute_name = 'color_0'

	            if not ((mobj.rendermode & hsd.RENDER_DIFFUSE_BITS) == hsd.RENDER_DIFFUSE_VTX):
	                diff = nodes.new('ShaderNodeRGB')
	                diff.outputs[0].default_value[:] = mat_diffuse_color
	                mix = nodes.new('ShaderNodeMixRGB')
	                mix.blend_type = 'ADD'
	                mix.inputs[0].default_value = 1
	                links.new(color.outputs[0], mix.inputs[1])
	                links.new(diff.outputs[0], mix.inputs[2])
	                color = mix

	        if (mobj.rendermode & hsd.RENDER_ALPHA_BITS) == hsd.RENDER_ALPHA_MAT:
	            alpha = nodes.new('ShaderNodeValue')
	            alpha.outputs[0].default_value = material.alpha
	        else:
	            alpha = nodes.new('ShaderNodeAttribute')
	            alpha.attribute_name = 'alpha_0'

	            if not (mobj.rendermode & hsd.RENDER_ALPHA_BITS) == hsd.RENDER_ALPHA_VTX:
	                mat_alpha = nodes.new('ShaderNodeValue')
	                mat_alpha.outputs[0].default_value = material.alpha
	                mix = nodes.new('ShaderNodeMath')
	                mix.operation = 'MULTIPLY'
	                links.new(alpha.outputs[0], mix.inputs[0])
	                links.new(mat_alpha.outputs[0], mix.inputs[1])
	                alpha = mix


	    last_color = color.outputs[0]
	    last_alpha = alpha.outputs[0]
	    last_bump  = None

	    for texdesc in textures:
	        if (texdesc.flag & hsd.TEX_COORD_MASK) == hsd.TEX_COORD_UV:
	            uv = nodes.new('ShaderNodeUVMap')
	            uv.uv_map = 'uvtex_' + str(texdesc.src - 4)
	            uv_output = uv.outputs[0]
	        elif (texdesc.flag & hsd.TEX_COORD_MASK) == hsd.TEX_COORD_REFLECTION:
	            uv = nodes.new('ShaderNodeTexCoord')
	            uv_output = uv.outputs[6]
	        else:
	            print('UV Type not supported: %X' % (texdesc.flag & hsd.TEX_COORD_MASK))
	            uv_output = None

	        mapping = nodes.new('ShaderNodeMapping')
	        mapping.vector_type = 'TEXTURE'
	        mapping.inputs[1].default_value = texdesc.translate #mapping.translation[:]
	        mapping.inputs[2].default_value = texdesc.rotate #mapping.rotate[:]
	        mapping.inputs[3].default_value = texdesc.scale #mapping.scale[:]

	        #blender UV coordinates are relative to the bottom left so we need to account for that
	        mapping.inputs[1].default_value[1] = 1 - (texdesc.scale[1] * (texdesc.translate[1] + 1))

	        #TODO: Is this correct?
	        if (texdesc.flag & hsd.TEX_COORD_MASK) == hsd.TEX_COORD_REFLECTION:
	            mapping.inputs[2].default_value[0] -= math.pi/2

	        texture = nodes.new('ShaderNodeTexImage')
	        texture.image = image_dict[texdesc.id]
	        texture.name = ("0x%X" % texdesc.id)
	        texture.name += ' flag: %X' % texdesc.flag
	        texture.name += (' image: 0x%X ' % (texdesc.imagedesc.image_ptr_id if texdesc.imagedesc else -1))
	        texture.name += (' tlut: 0x%X' % (texdesc.tlutdesc.id if texdesc.tlutdesc else -1))

	        texture.extension = 'EXTEND'
	        if texdesc.wrap_t == gx.GX_REPEAT:
	            texture.extension = 'REPEAT'

	        interp_dict = {
	            gx.GX_NEAR: 'Closest',
	            gx.GX_LINEAR: 'Linear',
	            gx.GX_NEAR_MIP_NEAR: 'Closest',
	            gx.GX_LIN_MIP_NEAR: 'Linear',
	            gx.GX_NEAR_MIP_LIN: 'Closest',
	            gx.GX_LIN_MIP_LIN: 'Cubic' #XXX use CUBIC?
	        }

	        if texdesc.lod:
	            texture.interpolation = interp_dict[texdesc.lod.minFilt]

	        if uv_output:
	            links.new(uv_output, mapping.inputs[0])
	        links.new(mapping.outputs[0], texture.inputs[0])

	        cur_color = texture.outputs[0]
	        cur_alpha = texture.outputs[1]
	        #do tev
	        if texdesc.tev:
	            tev = texdesc.tev
	            if tev.active & hsd.TOBJ_TEVREG_ACTIVE_COLOR_TEV:
	                inputs = [make_tev_input(nodes, texture, tev, i, True) for i in range(4)]
	                cur_color = make_tev_op(nodes, links, inputs, tev, True)

	            if tev.active & hsd.TOBJ_TEVREG_ACTIVE_ALPHA_TEV:
	                inputs = [make_tev_input(nodes, texture, tev, i, False) for i in range(4)]
	                cur_alpha = make_tev_op(nodes, links, inputs, tev, False)

	            texture.name += ' tev'
	        if texdesc.flag & hsd.TEX_BUMP:
	            #bumpmap
	            if last_bump:
	                #idk, just do blending for now to keep the nodes around
	                mix = nodes.new('ShaderNodeMixRGB')
	                mix.blend_type = 'MIX'
	                mix.inputs[0].default_value = texdesc.blending
	                links.new(last_bump, mix.inputs[1])
	                links.new(cur_color, mix.inputs[2])
	                last_bump = mix.outputs[0]
	            else:
	                last_bump = cur_color
	        else:
	            #do color
	            if (texdesc.flag & hsd.TEX_LIGHTMAP_MASK) & (hsd.TEX_LIGHTMAP_DIFFUSE | hsd.TEX_LIGHTMAP_EXT):
	                colormap = texdesc.flag & hsd.TEX_COLORMAP_MASK
	                if not (colormap == hsd.TEX_COLORMAP_NONE or
	                        colormap == hsd.TEX_COLORMAP_PASS):
	                    mix = nodes.new('ShaderNodeMixRGB')
	                    mix.blend_type = map_col_op_dict[colormap]
	                    mix.inputs[0].default_value = 1
	                    ###
	                    colormap_name_dict = {
	                    hsd.TEX_COLORMAP_NONE: 'TEX_COLORMAP_NONE',
	                    hsd.TEX_COLORMAP_PASS: 'TEX_COLORMAP_PASS',
	                    hsd.TEX_COLORMAP_REPLACE: 'TEX_COLORMAP_REPLACE',
	                    hsd.TEX_COLORMAP_ALPHA_MASK: 'TEX_COLORMAP_ALPHA_MASK',
	                    hsd.TEX_COLORMAP_RGB_MASK: 'TEX_COLORMAP_RGB_MASK',
	                    hsd.TEX_COLORMAP_BLEND: 'TEX_COLORMAP_BLEND',
	                    hsd.TEX_COLORMAP_ADD: 'TEX_COLORMAP_ADD',
	                    hsd.TEX_COLORMAP_SUB: 'TEX_COLORMAP_SUB',
	                    hsd.TEX_COLORMAP_MODULATE: 'TEX_COLORMAP_MODULATE'
	                    }
	                    mix.name = colormap_name_dict[colormap] + ' ' + str(texdesc.blending)
	                    ###
	                    if not colormap == hsd.TEX_COLORMAP_REPLACE:
	                        links.new(last_color, mix.inputs[1])
	                        links.new(cur_color, mix.inputs[2])
	                    if colormap == hsd.TEX_COLORMAP_ALPHA_MASK:
	                        links.new(cur_alpha, mix.inputs[0])
	                    elif colormap == hsd.TEX_COLORMAP_RGB_MASK:
	                        links.new(cur_color, mix.inputs[0])
	                    elif colormap == hsd.TEX_COLORMAP_BLEND:
	                        mix.inputs[0].default_value = texdesc.blending
	                    elif colormap == hsd.TEX_COLORMAP_REPLACE:
	                        links.new(cur_color, mix.inputs[1])
	                        mix.inputs[0].default_value = 0.0

	                    last_color = mix.outputs[0]
	            #do alpha
	            alphamap = texdesc.flag & hsd.TEX_ALPHAMAP_MASK
	            if not (alphamap == hsd.TEX_ALPHAMAP_NONE or
	                    alphamap == hsd.TEX_ALPHAMAP_PASS):
	                mix = nodes.new('ShaderNodeMixRGB')
	                mix.blend_type = map_alpha_op_dict[alphamap]
	                mix.inputs[0].default_value = 1
	                ###
	                alphamap_name_dict = {
	                hsd.TEX_ALPHAMAP_NONE: 'TEX_ALPHAMAP_NONE',
	                hsd.TEX_ALPHAMAP_PASS: 'TEX_ALPHAMAP_PASS',
	                hsd.TEX_ALPHAMAP_REPLACE: 'TEX_ALPHAMAP_REPLACE',
	                hsd.TEX_ALPHAMAP_ALPHA_MASK: 'TEX_ALPHAMAP_ALPHA_MASK',
	                hsd.TEX_ALPHAMAP_BLEND: 'TEX_ALPHAMAP_BLEND',
	                hsd.TEX_ALPHAMAP_ADD: 'TEX_ALPHAMAP_ADD',
	                hsd.TEX_ALPHAMAP_SUB: 'TEX_ALPHAMAP_SUB',
	                hsd.TEX_ALPHAMAP_MODULATE: 'TEX_ALPHAMAP_MODULATE'
	                }
	                mix.name = alphamap_name_dict[alphamap]
	                ###
	                if not alphamap == hsd.TEX_ALPHAMAP_REPLACE:
	                    links.new(last_alpha, mix.inputs[1])
	                    links.new(cur_alpha, mix.inputs[2])
	                if alphamap == hsd.TEX_ALPHAMAP_ALPHA_MASK:
	                    links.new(cur_alpha, mix.inputs[0])
	                elif alphamap == hsd.TEX_ALPHAMAP_BLEND:
	                    mix.inputs[0].default_value = texdesc.blending
	                elif alphamap == hsd.TEX_ALPHAMAP_REPLACE:
	                    links.new(cur_alpha, mix.inputs[1])

	                last_alpha = mix.outputs[0]

	    #final render settings, on the GameCube these would control how the rendered data is written to the EFB (Embedded Frame Buffer)

	    alt_blend_mode = 'NOTHING'

	    transparent_shader = False
	    if mobj.pedesc:
	        pedesc = mobj.pedesc
	        #PE (Pixel Engine) parameters can be given manually in this struct
	        #TODO: implement other custom PE stuff
	        #blend mode
	        #HSD_StateSetBlendMode    ((GXBlendMode) pe->type,
			#	      (GXBlendFactor) pe->src_factor,
			#	      (GXBlendFactor) pe->dst_factor,
			#	      (GXLogicOp) pe->logic_op);
	        if pedesc.type == gx.GX_BM_NONE:
	            pass #source data just overwrites EFB data (Opaque)
	        elif pedesc.type == gx.GX_BM_BLEND:
	            #dst_pix_clr = src_pix_clr * src_factor + dst_pix_clr * dst_factor
	            if pedesc.dst_factor == gx.GX_BL_ZERO:
	                #destination is completely overwritten
	                if pedesc.src_factor == gx.GX_BL_ONE:
	                    pass #same as GX_BM_NONE
	                elif pedesc.src_factor == gx.GX_BL_ZERO:
	                    #destination is set to 0
	                    black = nodes.new('ShaderNodeRGB')
	                    black.outputs[0].default_value[:] = [0,0,0,1]
	                    last_color = black.outputs[0]
	                elif pedesc.src_factor == gx.GX_BL_DSTCLR:
	                    #multiply src and dst
	                    #mat.blend_method = 'MULTIPLY'
	                    alt_blend_mode = 'MULTIPLY'
	                elif pedesc.src_factor == gx.GX_BL_SRCALPHA:
	                    #blend with black by alpha
	                    blend = nodes.new('ShaderNodeMixRGB')
	                    links.new(last_alpha, blend.inputs[0])
	                    blend.inputs[1].default_value = [0,0,0,0xFF]
	                    links.new(last_color, blend.inputs[2])
	                    last_color = blend.outputs[0]
	                elif pedesc.src_factor == gx.INVSRCALPHA:
	                    #same as above with inverted alpha
	                    blend = nodes.new('ShaderNodeMixRGB')
	                    links.new(last_alpha, blend.inputs[0])
	                    blend.inputs[2].default_value = [0,0,0,0xFF]
	                    links.new(last_color, blend.inputs[1])
	                    last_color = blend.outputs[0]
	                else:
	                    #can't be properly approximated with Eevee or Cycles
	                    pass
	            elif pedesc.dst_factor == gx.GX_BL_ONE:
	                if pedesc.src_factor == gx.GX_BL_ONE:
	                    #Add src and dst
	                    #mat.blend_method = 'ADD'
	                    alt_blend_mode = 'ADD'
	                elif pedesc.src_factor == gx.GX_BL_ZERO:
	                    #Material is invisible
	                    transparent_shader = True
	                    mat.blend_method = 'HASHED'
	                    invisible = nodes.new('ShaderNodeValue')
	                    invisible.outputs[0].default_value = 0
	                    last_alpha = invisible.outputs[0]
	                elif pedesc.src_factor == gx.GX_BL_SRCALPHA:
	                    #add alpha blended color
	                    transparent_shader = True
	                    #mat.blend_method = 'ADD'
	                    alt_blend_mode = 'ADD'
	                    #manually blend color
	                    blend = nodes.new('ShaderNodeMixRGB')
	                    links.new(last_alpha, blend.inputs[0])
	                    blend.inputs[1].default_value = [0,0,0,0xFF]
	                    links.new(last_color, blend.inputs[2])
	                    last_color = blend.outputs[0]
	                elif pedesc.src_factor == gx.GX_BL_INVSRCALPHA:
	                    #add inverse alpha blended color
	                    transparent_shader = True
	                    #mat.blend_method = 'ADD'
	                    alt_blend_mode = 'ADD'
	                    #manually blend color
	                    blend = nodes.new('ShaderNodeMixRGB')
	                    links.new(last_alpha, blend.inputs[0])
	                    blend.inputs[2].default_value = [0,0,0,0xFF]
	                    links.new(last_color, blend.inputs[1])
	                    last_color = blend.outputs[0]
	                else:
	                    #can't be properly approximated with Eevee or Cycles
	                    pass
	            elif (pedesc.dst_factor == gx.GX_BL_INVSRCALPHA and pedesc.src_factor == gx.GX_BL_SRCALPHA):
	                #Alpha Blend
	                transparent_shader = True
	                mat.blend_method = 'HASHED'
	            elif (pedesc.dst_factor == gx.GX_BL_SRCALPHA and pedesc.src_factor == gx.GX_BL_INVSRCALPHA):
	                #Inverse Alpha Blend
	                transparent_shader = True
	                mat.blend_method = 'HASHED'
	                factor = nodes.new('ShaderNodeMath')
	                factor.operation = 'SUBTRACT'
	                factor.inputs[0].default_value = 1
	                factor.use_clamp = True
	                links.new(last_alpha, factor.inputs[1])
	                last_alpha = factor.outputs[0]
	            else:
	                #can't be properly approximated with Eevee or Cycles
	                pass
	        elif pedesc.type == gx.GX_BM_LOGIC:
	            if pedesc.op == gx.GX_LO_CLEAR:
	                #destination is set to 0
	                black = nodes.new('ShaderNodeRGB')
	                black.outputs[0].default_value[:] = [0,0,0,1]
	                last_color = black.outputs[0]
	            elif pedesc.op == gx.GX_LO_SET:
	                #destination is set to 1
	                white = nodes.new('ShaderNodeRGB')
	                white.outputs[0].default_value[:] = [1,1,1,1]
	                last_color = white.outputs[0]
	            elif pedesc.op == gx.GX_LO_COPY:
	                pass #same as GX_BM_NONE ?
	            elif pedesc.op == gx.GX_LO_INVCOPY:
	                #invert color ?
	                invert = nodes.new('ShaderNodeInvert')
	                links.new(last_color, invert.inputs[1])
	                last_color = invert.outputs[0]
	            elif pedesc.op == gx.GX_LO_NOOP:
	                #Material is invisible
	                transparent_shader = True
	                mat.blend_method = 'HASHED'
	                invisible = nodes.new('ShaderNodeValue')
	                invisible.outputs[0].default_value = 0
	                last_alpha = invisible.outputs[0]
	            else:
	                #can't be properly approximated with Eevee or Cycles
	                pass
	        elif pedesc.type == gx.GX_BM_SUBTRACT:
	            pass #not doable right now
	        else:
	            error_log('Unknown Blend Mode: %X' % pedesc.type)
	    else:
	        #TODO:
	        #use the presets from the rendermode flags
	        if mobj.rendermode & hsd.RENDER_XLU:
	            transparent_shader = True
	            mat.blend_method = 'HASHED'

	    #output shader
	    shader = nodes.new('ShaderNodeBsdfPrincipled')
	    #specular
	    if mobj.rendermode & hsd.RENDER_SPECULAR:
	        shader.inputs[5].default_value = mobj.mat.shininess / 50
	    else:
	        shader.inputs[5].default_value = 0
	    #specular tint
	    shader.inputs[6].default_value = .5
	    #roughness
	    shader.inputs[7].default_value = .5

	    #diffuse color
	    links.new(last_color, shader.inputs[0])

	    #alpha
	    if transparent_shader:
	        #
	        #alpha_factor = nodes.new('ShaderNodeMath')
	        #alpha_factor.operation = 'POWER'
	        #alpha_factor.inputs[1].default_value = 3
	        #links.new(last_alpha, alpha_factor.inputs[0])
	        #last_alpha = alpha_factor.outputs[0]
	        #
	        links.new(last_alpha, shader.inputs[18])

	    #normal
	    if last_bump:
	        bump = nodes.new('ShaderNodeBump')
	        bump.inputs[1].default_value = 1
	        links.new(last_bump, bump.inputs[2])
	        links.new(bump.outputs[0], shader.inputs[19])

	    #Add Additive or multiplicative alpha blending, since these don't have explicit options in 2.81 anymore
	    if (alt_blend_mode == 'ADD'):
	        mat.blend_method = 'BLEND'
	        #using emissive shader, unfortunately this will obviously override all the principled settings
	        e = nodes.new('ShaderNodeEmission')
	        #is this really right ? comes from blender release notes
	        e.inputs[1].default_value = 1.9
	        t = nodes.new('ShaderNodeBsdfTransparent')
	        add = nodes.new('ShaderNodeAddShader')
	        links.new(last_color, e.inputs[0])
	        links.new(e.outputs[0], add.inputs[0])
	        links.new(t.outputs[0], add.inputs[1])
	        shader = add
	    elif (alt_blend_mode == 'MULTIPLY'):
	        mat.blend_method = 'BLEND'
	        #using transparent shader, unfortunately this will obviously override all the principled settings
	        t = nodes.new('ShaderNodeBsdfTransparent')
	        links.new(last_color, t.inputs[0])
	        shader = t

	    #output to Material
	    links.new(shader.outputs[0], output.inputs[0])

	    output.name = 'Rendermode : 0x%X' % mobj.rendermode
	    output.name += ' Transparent: ' + ('True' if transparent_shader else 'False')
	    output.name += ' Pedesc: ' + (pedesc_type_dict[mobj.pedesc.type] if mobj.pedesc else 'False')
	    if mobj.pedesc and mobj.pedesc.type == gx.GX_BM_BLEND:
	        output.name += ' ' + pedesc_src_factor_dict[mobj.pedesc.src_factor] + ' ' + pedesc_dst_factor_dict[mobj.pedesc.dst_factor]

	    return mat

#normalize u8 to float
#only used for color so we can do srgb conversion here
def normcolor(x):
    if len(x) > 2:
        color = [c / 255 for c in x]
        return tolin(color)
    else:
        type = x[1]
        val = x[0] / 255
        if type == 'R' or type == 'G' or type == 'B':
            return tolin([val])[0]
        elif type == 'A':
            return val













