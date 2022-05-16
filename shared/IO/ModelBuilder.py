import bpy
import math

from ..Constants import *
from ..Errors import *
from ..Nodes import *

class ModelBuilder(object):

	def __init__(self, context, sections, options):
		# Settings chosen for the parser
		# - "ik_hack"   : A boolean for whether or not to scale down bones so ik works correctly
		# - "max_frame" : An integer for the maximum number of frames to read from an animation, 0 for no limit
		# - "verbose"   : Prints more output for debugging purposes
		self.options = options

		self.context = context
		self.sections = sections

		self.armature_count = 0
		self.bone_count = 0

		self.models = []
		self.lights = []
		self.cameras = []
		self.fogs = []

		# Create lookup tables for textures, materials and meshes
		# so we can easily reference them from other nodes later.
		self.textures = {}
		self.materials = {}
		self.meshes = {}

		# Sometimes there are sets which are separated across multiple sections.
		# In this scenario we can build up the model set bit by bit.
		disjoint_modelset = ModelSet.emptySet()
		disjoint_cameraset = CameraSet.emptySet()
		disjoint_lightset = LightSet.emptySet()


		for section in sections:
			if section.root_node == None:
				continue

			if isinstance(section.root_node, Joint):
				disjoint_modelset.root_joint = section.root_node

			elif isinstance(section.root_node, AnimationJoint):
				disjoint_modelset.animated_joints.append(section.root_node)

			elif isinstance(section.root_node, MaterialAnimationJoint):
				disjoint_modelset.animated_material_joints.append(section.root_node)

			elif isinstance(section.root_node, ShapeAnimationJoint):
				disjoint_modelset.animated_shape_joints.append(section.root_node)

			elif isinstance(section.root_node, Camera):
				disjoint_cameraset.camera = section.root_node

			elif isinstance(section.root_node, CameraAnimation):
				disjoint_cameraset.animations.append(section.root_node)

			elif isinstance(section.root_node, CameraSet):
				self.cameras.append(section.root_node)

			elif isinstance(section.root_node, Light):
				disjoint_lightset.light = section.root_node

			elif isinstance(section.root_node, LightAnimation):
				disjoint_lightset.animations.append(section.root_node)

			elif isinstance(section.root_node, LightSet):
				self.lights.append(section.root_node)

			elif isinstance(section.root_node, SceneData):
				scene_data = section.root_node
				self.cameras.append(scene_data.camera)
				self.fogs.append(scene_data.fog)
				self.lights += scene_data.lights
				self.models += scene_data.models
			
			# Add certain node types to the look up tables for future reference
			all_nodes = section.root_node.toList()
			texture_nodes = list(filter(lambda node: isinstance(node, Texture), all_nodes))
			for texture in texture_nodes:
				self.textures[texture.id] = texture.image_data

			material_nodes = list(filter(lambda node: isinstance(node, MaterialObject), all_nodes))
			for mobject in material_nodes:
				self.materials[mobject.id] = self.make_material(mobject)

			mesh_nodes = list(filter(lambda node: isinstance(node, Mesh), all_nodes))
			for mesh in mesh_nodes:
				pobject = mesh.pobject
				while pobject:
					mesh_object = self.make_mesh(pobject)
					# Add material
					material = self.materials.get(mesh.mobject.id)
					mesh_object.data.materials.append(material)
					self.meshes[pobject.id] = mesh_object
					pobject = pobject.next
					

		if disjoint_modelset.root_joint != None:
			self.modelsets.append(disjoint_modelset)

		if disjoint_cameraset.camera != None:
			self.cameras.append(disjoint_cameraset)

		if disjoint_lightset.light != None:
			self.lightsets.append(disjoint_lightset)

	def build(self):
		if self.options.get("verbose"):
			print("Building model")

		for model in self.models:
			self.importModel(model)

		for light in self.lights:
			self.importLight(light)

		for camera in self.cameras:
			self.importCamera(camera)

		for fog in self.fogs:
			self.importFog(fog)


	# TODO: complete implementation
	def importModel(self, model):
		if model == None:
			return

		root_joint = model.root_joint
		armature = self.createArmature()

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

	def createArmature(self, root_joint):
		if root_joint == None:
			return None

		armature_name = None
		if root_joint.name:
		    armature_name = 'Armature_' + root_joint.name
		else:
		    armature_name = 'Armature_' + str(self.armature_count)

		self.armature_count += 1

		armature_data = bpy.data.armatures.new(name = armature_name)
		armature = bpy.data.objects.new(name = armature_name, object_data = armature_data)

		#TODO: Seperate Object hierarchy from armatures via Skeleton flags
		#rotate armature into proper orientation
		#needed due to different coordinate systems
		armature.matrix_basis = Matrix.Translation(Vector((0,0,0)))
		self.translate_coordinate_system(armature)

		#make an instance in the scene
		bpy.context.scene.collection.objects.link(armature)
		armature_object = armature
		armature_object.select_set(True)

		# Using the hack. The bones will be too small to see otherwise
		if self.options.get("ik_hack"):
		    armature_data.display_type = 'STICK'

		bpy.context.view_layer.objects.active = armature

		#add bones
		bones = root_joint.build_bone_hierarchy(self, None, None)

		bpy.ops.object.mode_set(mode = 'POSE')
		self.add_geometry(armature, bones)
		self.add_contraints(armature, bones)
		self.add_instances(armature, bones, mesh_dict)

		bpy.context.view_layer.update()
		bpy.ops.object.mode_set(mode = 'OBJECT')

		return armature

	def translate_coordinate_system(self, obj):
	    #correct orientation due to coordinate system differences
	    obj.matrix_basis @= Matrix.Rotation(math.pi / 2, 4, [1.0,0.0,0.0])

	def add_geometry(self, armature, bones):
	    #TODO: Find out what to do with particles ?
	    for bone in bones:
	        if bone.flags & JOBJ_INSTANCE:
	            # We can't copy objects from other bones here since they may not be parented yet
	            pass
	        else:
	            if not bone.flags & (JOBJ_PTCL | JOBJ_SPLINE):
	                mesh_object = bone.property
	                while dobj:
	                    pobj = mesh_object.pobj
	                    while pobj:
	                        mesh = self.meshes[pobj.id]
	                        mesh.parent = armature
	                        # Apply deformation and rigid transformations temporarily stored in the hsd_mesh.
	                        # This is done here because the meshes are created before the object hierarchy exists.
	                        self.apply_bone_weights(mesh, pobj, bone, armature)
	                        # Reemove degenerate geometry.
	                        # Most of the time it's generated from tristrips changing orientation (for example in a plane).
	                        mesh.data.validate(verbose=False, clean_customdata=False)
	                        pobj = pobj.next
	                    mesh_object = mesh_object.next

	def apply_bone_weights(self, mesh, hsd_mesh, hsd_bone, armature):
		# Apply weights now that the bones actually exist
		bpy.context.view_layer.objects.active = mesh

		#TODO: This is inefficient, I should probably sort the vertices by the envelope index beforehand

		if hsd_mesh.skin[0]:
		    #envelope
		    bpy.ops.object.mode_set(mode = 'EDIT')
		    joint_groups = {}
		    matrices = []
		    envelopes = hsd_mesh.skin[1]
		    for envelope in envelopes:
		        matrix = Matrix([[0] * 4] * 4)
		        coord = envelope_coord_system(hsd_bone)
		        if envelope[0][0] == 1.0:
		            joint = envelope[0][1]
		            if not joint.id in joint_groups:
		                group = mesh.vertex_groups.new(name=joint.temp_name)
		                joint_groups[joint.id] = group
		            if coord:
		                matrix = joint.temp_matrix @ get_hsd_invbind(joint)
		            else:
		                matrix = joint.temp_matrix
		        else:
		            for weight, joint in envelope:
		                if not joint.id in joint_groups:
		                    group = mesh.vertex_groups.new(name=joint.temp_name)
		                    joint_groups[joint.id] = group
		                matrix += (weight * (joint.temp_matrix @ get_hsd_invbind(joint)))
		        if coord:
		            matrix = matrix @ coord
		        matrices.append(matrix)

		    bpy.ops.object.mode_set(mode = 'OBJECT')

		    indices = hsd_mesh.skin[0]
		    for vertex, index in indices:
		        mesh.data.vertices[vertex].co = matrices[index] @ mesh.data.vertices[vertex].co
		        for weight, joint in envelopes[index]:
		            joint_groups[joint.id].add([vertex], weight, 'REPLACE')

		    for matrix in matrices:
		        print(matrix)

		    if hsd_mesh.normals:
		        #XXX: Is this actually needed?
		        matrix_indices = dict(indices)
		        normal_matrices = []
		        for matrix in matrices:
		            normal_matrix = matrix.to_3x3()
		            normal_matrix.invert()
		            normal_matrix.transpose()
		            normal_matrices.append(normal_matrix.to_4x4())

		        for loop in mesh.data.loops:
		            hsd_mesh.normals[loop.index] = (normal_matrices[matrix_indices[loop.vertex_index]] @ Vector(hsd_mesh.normals[loop.index])).normalized()[:]
		        mesh.data.normals_split_custom_set(hsd_mesh.normals)

		else:
		    if hsd_mesh.skin[1]:
		        #No idea if this is right, don't have any way to test right now
		        matrix = Matrix([[0] * 4] * 4)
		        group0 = mesh.vertex_groups.new(name=hsd_bone.temp_name)
		        matrix += 0.5 * (hsd_bone.temp_matrix @ get_hsd_invbind(hsd_bone))
		        joint = hsd_mesh.skin[1]
		        group1 = mesh.vertex_groups.new(name=hsd_bone.temp_name)
		        matrix += 0.5 * (joint.temp_matrix @ get_hsd_invbind(hsd_bone))

		        mesh.matrix_global = matrix

		        group0.add([v.index for v in mesh.data.vertices], 0.5, 'REPLACE')
		        group1.add([v.index for v in mesh.data.vertices], 0.5, 'REPLACE')

		        if hsd_mesh.normals:
		            for loop in mesh.data.loops:
		                matrix = matrix.inverted().transposed()
		                hsd_mesh.normals[loop.index] = (matrix @ Vector(hsd_mesh.normals[loop.index])).normalized()[:]
		            mesh.data.normals_split_custom_set(hsd_mesh.normals)

		    else:
		        mesh.matrix_local = hsd_bone.temp_matrix #* get_hsd_invbind(hsd_bone)
		        #TODO: get matrix relative to parent bone and set parent mode to bone
		        group = mesh.vertex_groups.new(name=hsd_bone.temp_name)
		        group.add([v.index for v in mesh.data.vertices], 1.0, 'REPLACE')
		        if hsd_mesh.normals:
		            mesh.data.normals_split_custom_set(hsd_mesh.normals)


		mod = mesh.modifiers.new('Skinmod', 'ARMATURE')
		mod.object = armature
		mod.use_bone_envelopes = False
		mod.use_vertex_groups = True

	def make_mesh(self, pobj):
		name = ''
		if pobj.name:
			name = pobj.name

		display_list = pobj.display_list
		vertex_list = pobj.vertex_list.vertices
		display_list_size = pobj.display_list_chunk_count

		position_vertex_index = None #index of the vtxdesc that holds vertex position data
		for i in range(len(vertex_list)):
			vertex = vertex_list[i]
			if vertex.attribute == GX_VA_POS:
			    position_vertex_index = i

		if position_vertex_index == None:
		    raise MeshWithoutPositionError

		#vertices, faces = read_geometry(vtxdesclist, displist, i)
		#TODO: move the loop here to avoid redundancy
		sources, face_lists, normals = self.read_geometry(vertex_list, display_list, display_list_size)
		vertices = sources[position_vertex_index]
		faces = facelists[position_vertex_index]

		# Create mesh and object
		mesh = bpy.data.meshes.new('Mesh_' + name)
		mesh_object = bpy.data.objects.new(name, mesh)
		mesh_object.location = Vector((0,0,0))
		# Link object to scene
		bpy.context.scene.collection.objects.link(mesh_object)

		# Create mesh from given verts, edges, faces. Either edges or
		# faces should be [], or you ask for problems
		mesh.from_pydata(vertices, [], faces)

		if pobj.property:
		    type = pobj.flags & POBJ_TYPE_MASK
		    if type == POBJ_SHAPEANIM:
		        shape_set = pobj.property
		        self.make_shapeset(mesh_object, shape_set, normdicts[position_vertex_index])
		        self.make_rigid_skin(pobj)
		    elif type == POBJ_ENVELOPE:
		        envelope_list = pobj.property
		        envelope_vertex_index = None
		        for index, vertex in enumerate(vertex_list):
		            if vertex.attribute == GX_VA_PNMTXIDX:
		                envelope_vertex_index = index
		        if envelope_vertex_index != None:
		            self.make_deform_skin(pobj, envelope_list, sources[envelope_vertex_index], face_lists[envelope_vertex_index], faces)
		        else:
		            raise InvalidEnvelopeError

		    else:
		        # Make skin
		        # Deprecated, probably still used somewhere though
		        joint = pobj.property
		        self.make_skin(pobj, joint)

		else:
		    self.make_rigid_skin(pobj)


		#mesh.calc_normals()
		pobj.normals = None
		for index, vertex in enumerate(vertex_list):
		    if vertex.is_tex():
		        uvlayer = self.make_texture_layer(mesh, vertex, sources[index], face_lists[index])
		    elif vertex.attribute == GX_VA_NRM or vertex.attribute == GX_VA_NBT:
		        self.assign_normals_to_mesh(pobj, mesh, vertex, sources[index], facelists[index])
		        mesh.use_auto_smooth = True
		    elif (vertex.attribute == GX_VA_CLR0 or
		          vertex.attribute == GX_VA_CLR1):
		        self.add_color_layer(mesh, vertex, sources[index], face_lists[index])

		# Update mesh with new data
		# Remove degenerate faces (These mostly occur due to triangle strips creating invisible faces when changing orientation)
		mesh.update(calc_edges = True, calc_edges_loose = False)

		return mesh_object

	# TODO: fix up implementation. Copy from make_approx_cycles_material.
	def make_material(self, material_object):
	    material = material_object.material
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
	    texture = material_object.texture
	    # Note: there shouldn't be more than 7 textures per material
	    while texture:
	    	# Check if texture is enabled in the material
	        if material_object.render_mode & (1 << (len(textures) + 4)):
	            textures.append(texture)
	        texture = texture.next

	    alpha = None
	    if material_object.render_mode & RENDER_DIFFUSE:
	        color = nodes.new('ShaderNodeRGB')
	        if (material_object.render_mode & RENDER_DIFFUSE_BITS) == RENDER_DIFFUSE_VTX:
	            color.outputs[0].default_value[:] = [1,1,1,1]
	        else:
	            color.outputs[0].default_value[:] = diffuse_color

	        alpha = nodes.new('ShaderNodeValue')
	        if (material_object.render_mode & RENDER_ALPHA_BITS) == RENDER_ALPHA_VTX:
	            alpha.outputs[0].default_value = 1
	        else:
	            alpha.outputs[0].default_value = material.alpha
	    else:
	        if (material_object.render_mode & CHANNEL_FIELD) == RENDER_DIFFUSE_MAT:
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

	            if not ((material_object.render_mode & RENDER_DIFFUSE_BITS) == RENDER_DIFFUSE_VTX):
	                diffuse = nodes.new('ShaderNodeRGB')
	                diffuse.outputs[0].default_value[:] = diffuse_color
	                mix = nodes.new('ShaderNodeMixRGB')
	                mix.blend_type = 'ADD'
	                mix.inputs[0].default_value = 1
	                links.new(color.outputs[0], mix.inputs[1])
	                links.new(diffuse.outputs[0], mix.inputs[2])
	                color = mix

	        if (material_object.render_mode & RENDER_ALPHA_BITS) == RENDER_ALPHA_MAT:
	            alpha = nodes.new('ShaderNodeValue')
	            alpha.outputs[0].default_value = material.alpha
	        else:
	            alpha = nodes.new('ShaderNodeAttribute')
	            alpha.attribute_name = 'alpha_0'

	            if not (material_object.render_mode & RENDER_ALPHA_BITS) == RENDER_ALPHA_VTX:
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
	    if material_object.pixel_engine_data:
	        pixel_engine_data = material_object.pixel_engine_data
	        # PE (Pixel Engine) parameters can be given manually in this struct
	        # TODO: implement other custom PE stuff
	        # Blend mode
	        # HSD_StateSetBlendMode    ((GXBlendMode) pe->type,
			#	      (GXBlendFactor) pixel_engine_data->source_factor,
			#	      (GXBlendFactor) pixel_engine_data->destination_factor,
			#	      (GXLogicOp) pixel_engine_data->logic_op);
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
	        if material_object.render_mode & RENDER_XLU:
	            transparent_shader = True
	            blender_material.blend_method = 'HASHED'

	    # Output shader
	    shader = nodes.new('ShaderNodeBsdfPrincipled')
	    # Specular
	    if material_object.render_mode & RENDER_SPECULAR:
	        shader.inputs[5].default_value = material_object.material.shininess / 50
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

	    output.name = 'Rendermode : 0x%X' % material_object.render_mode
	    output.name += ' Transparent: ' + ('True' if transparent_shader else 'False')
	    output.name += ' PixelEngine: ' + (str(pixel_engine_data.type) if material_object.pixel_engine_data else 'False')
	    if material_object.pixel_engine_data and material_object.pixel_engine_data.type == GX_BM_BLEND:
	        output.name += ' ' + str(pixel_engine_data.source_factor) + ' ' + str(pixel_engine_data.destination_factor)

	    return blender_material

	def add_contraints(self, armature, bones):
		for hsd_joint in bones:
			if hsd_joint.flags & JOBJ_TYPE_MASK == JOBJ_EFFECTOR:
			    if not hsd_joint.temp_parent:
			        raise IKEffectorWithoutParentError
			        continue
			    if hsd_joint.temp_parent.flags & JOBJ_TYPE_MASK == JOBJ_JOINT2:
			        chain_length = 3
			        pole_data_joint = hsd_joint.temp_parent.temp_parent
			    elif hsd_joint.temp_parent.flags & JOBJ_TYPE_MASK == JOBJ_JOINT1:
			        chain_length = 2
			        pole_data_joint = hsd_joint.temp_parent
			    target_robj = robj_get_by_type(hsd_joint, 0x10000000, 1)
			    poletarget_robj = robj_get_by_type(pole_data_joint, 0x10000000, 0)
			    length_robj = robj_get_by_type(hsd_joint.temp_parent, 0x40000000, 0)
			    if not length_robj:
			        notice_output("No Pole angle and bone length constraint on IK Effector Parent")
			        continue
			    bone_length = length_robj.val0
			    pole_angle = length_robj.val1
			    if length_robj.flags & 0x4:
			        pole_angle += math.pi #+180°
			    #This is a hack needed due to how the IK systems differ
			    #May break on models using a different exporter than the one used for XD/Colosseum
			    #(Or just some inconveniently placed children)
			    effector = armature.data.bones[hsd_joint.temp_name]
			    effector_pos = Vector(effector.matrix_local.translation)
			    effector_name = effector.name
			    bpy.context.view_layer.objects.active = armature
			    bpy.ops.object.mode_set(mode = 'EDIT')
			    position = Vector(effector.parent.matrix_local.translation)
			    direction = Vector(effector.parent.matrix_local.col[0][0:3]).normalized()
			    direction *= bone_length * effector.parent.matrix_local.to_scale()[0]
			    position += direction
			    #XXX contrary to documentation, .translate() doesn't seem to exist on EditBones in 2.81
			    #Swap this back when this gets fixed
			    #armature.data.edit_bones[effector_name].translate(position - effector_pos)
			    headpos = Vector(armature.data.edit_bones[effector_name].head[:]) + (position - effector_pos)
			    armature.data.edit_bones[effector_name].head[:] = headpos[:]
			    tailpos = Vector(armature.data.edit_bones[effector_name].tail[:]) + (position - effector_pos)
			    armature.data.edit_bones[effector_name].tail[:] = tailpos[:]
			    #
			    """
			    true_effector = effector
			    distance = abs(effector.head.length - bone_length)
			    for child in armature.data.bones[hsd_joint.temp_parent.temp_name].children:
			        l = abs(child.head.length - bone_length)
			        if l < distance:
			            true_effector = child
			            distance = l
			    """
			    bpy.ops.object.mode_set(mode = 'POSE')
			    #if hsd_joint.temp_parent.flags & JOBJ_SKELETON:
			    #adding the constraint

			    c = armature.pose.bones[effector_name].constraints.new(type = 'IK')
			    c.chain_count = chain_length
			    if target_robj:
			        c.target = armature
			        c.subtarget = target_robj.u.temp_name
			        if poletarget_robj:
			            c.pole_target = armature
			            c.pole_subtarget = poletarget_robj.u.temp_name
			            c.pole_angle = pole_angle
			    #else:
			    #    notice_output("No Pos constraint RObj on IK Effector")
			    #else:
			    #    notice_output("Adding IK contraint to Bone without Bone parents has no effect")

	interpolation_name_by_gx_constant = {
        GX_NEAR: 'Closest',
        GX_LINEAR: 'Linear',
        GX_NEAR_MIP_NEAR: 'Closest',
        GX_LIN_MIP_NEAR: 'Linear',
        GX_NEAR_MIP_LIN: 'Closest',
        GX_LIN_MIP_LIN: 'Cubic'
    }

	pedesc_src_factor_dict = {
		GX_BL_ZERO        : 'GX_BL_ZERO',
		GX_BL_ONE         : 'GX_BL_ONE',
		GX_BL_DSTCLR      : 'GX_BL_DSTCLR',
		GX_BL_INVDSTCLR   : 'GX_BL_INVDSTCLR',
		GX_BL_SRCALPHA    : 'GX_BL_SRCALPHA',
		GX_BL_INVSRCALPHA : 'GX_BL_INVSRCALPHA',
		GX_BL_DSTALPHA    : 'GX_BL_DSTALPHA',
		GX_BL_INVDSTALPHA : 'GX_BL_INVDSTALPHA',
	}

	pedesc_dst_factor_dict = {
		GX_BL_ZERO        : 'GX_BL_ZERO',
		GX_BL_ONE         : 'GX_BL_ONE',
		GX_BL_SRCCLR      : 'GX_BL_SRCCLR',
		GX_BL_INVSRCCLR   : 'GX_BL_INVSRCCLR',
		GX_BL_SRCALPHA    : 'GX_BL_SRCALPHA',
		GX_BL_INVSRCALPHA : 'GX_BL_INVSRCALPHA',
		GX_BL_DSTALPHA    : 'GX_BL_DSTALPHA',
		GX_BL_INVDSTALPHA : 'GX_BL_INVDSTALPHA',
	}

	pedesc_type_dict = {
	    GX_BM_NONE     : 'GX_BM_NONE',
	    GX_BM_BLEND    : 'GX_BM_BLEND',
	    GX_BM_LOGIC    : 'GX_BM_LOGIC',
	    GX_BM_SUBTRACT : 'GX_BM_SUBTRACT',
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








