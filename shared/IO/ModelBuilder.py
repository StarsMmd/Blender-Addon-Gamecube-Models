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
			print("Building model from section:", self.section.section_name)

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
		vertex_list = pobj.vtxdesclist
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

	# TODO: fix up implementation. Copy from approximateCyclesMaterial.
	def make_material(self, material_object):
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

	    mat_diffuse_color = material.diffuse

	    if mobj.pedesc:
	        pedesc = mobj.pedesc

	    textures = []
	    toon = None
	    tex_num = 0
	    texdesc = mobj.texdesc
	    while texdesc:
	        #if texdesc.flag & hsd.TEX_COORD_TOON:
	        #    toon = texdesc

	        #XXX:
	        if texdesc.tev:
	            tev = texdesc.tev

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

	def add_contraints(self, armature, bones):
		for hsd_joint in bones:
			if hsd_joint.flags & JOBJ_TYPE_MASK == JOBJ_EFFECTOR:
			    if not hsd_joint.temp_parent:
			        raise IKEffectorWithoutParentError
			        continue
			    if hsd_joint.temp_parent.flags & hsd.JOBJ_TYPE_MASK == hsd.JOBJ_JOINT2:
			        chain_length = 3
			        pole_data_joint = hsd_joint.temp_parent.temp_parent
			    elif hsd_joint.temp_parent.flags & hsd.JOBJ_TYPE_MASK == hsd.JOBJ_JOINT1:
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
			    #if hsd_joint.temp_parent.flags & hsd.JOBJ_SKELETON:
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












