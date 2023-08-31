import bpy
import math
from mathutils import Matrix, Euler, Vector

from ..Mesh import *
from ...Node import Node
from ....Constants import *

# Model Set
class ModelSet(Node):
    class_name = "Model Set"
    fields = [
        ('root_joint', 'Joint'),
        ('animated_joints', 'AnimationJoint[]'),
        ('animated_material_joints', 'MaterialAnimationJoint[]'),
        ('animated_shape_joints', 'ShapeAnimationJoint[]')
    ]

    @classmethod
    def emptySet(cls):
        new_node = ModelSet(0, None)
        new_node.root_joint = None
        new_node.animated_joints = []
        new_node.animated_material_joints = []
        new_node.animated_shape_joints = []
        return new_node

    def build(self, builder):
        self._createArmature(builder)

        # n_a = len(self.animated_joints) if self.animated_joints else 0
        # n_m = len(self.animated_material_joints) if self.animated_material_joints else 0
        # n_s = len(self.animated_shape_joints) if self.animated_shape_joints else 0

        # self.animation_count = max(n_a, n_m, n_s)

        # for i in range(self.animation_count):
        #     if self.animated_joints:
        #         animated_joint = self.animated_joints[i]
        #         if animated_joint.animation or animated_joint.child or animated_joint.next:
        #             action = bpy.data.actions.new(os.path.basename(filepath) + '_' + str(self.id) + ' Animation: ' + str(i))
        #             action.use_fake_user = True
        #             bpy.types.PoseBone.custom_40 = bpy.props.FloatProperty(name="40")
        #             add_bone_animation_total(armature, root_joint, modelset.animjoints[i], action)
        #     #TODO: figure out how to pack this into a single track with the above or something
        #     #if modelset.matanimjoints:
        #     #    add_material_animation(material_dict, modelset.matanimjoints[i], action)
        #     #if modelset.shapeanimjoints:
        #     #    add_shape_animation(mesh_dict, modelset.shapeanimjoints[i], action)

    def _createArmature(self, builder):
        if self.root_joint == None:
            return

        armature_name = None
        if self.root_joint.name:
            armature_name = 'Armature_' + self.root_joint.name
        else:
            armature_name = 'Armature_' + str(builder.armature_count)

        self.id = builder.armature_count
        builder.armature_count += 1

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
        if builder.options.get("ik_hack"):
            armature_data.display_type = 'STICK'

        bpy.context.view_layer.objects.active = armature

        # Add bones
        self.bone_count = 0
        bones = self.root_joint.buildBoneHierarchy(builder, self, None, None, armature_data)

        bpy.ops.object.mode_set(mode = 'POSE')

        # Add meshes
        self.mesh_count = 0
        self.addGeometry(builder, armature, bones)

        # self.addConstraints(armature, bones)
        # self.addInstances(armature, bones, mesh_dict)

        bpy.context.view_layer.update()
        bpy.ops.object.mode_set(mode = 'OBJECT')

        return armature

    def translate_coordinate_system(self, obj):
        #correct orientation due to coordinate system differences
        obj.matrix_basis @= Matrix.Rotation(math.pi / 2, 4, [1.0,0.0,0.0])

    def addGeometry(self, builder, armature, bones):
        for bone in bones:
            # TODO: Find out what to do with particles ?
            if bone.flags & JOBJ_INSTANCE:
                # We can't copy objects from other bones here since they may not be parented yet
                pass

            else:
                if isinstance(bone.property, Mesh):
                    mesh = bone.property
                    while mesh:
                        pobj = mesh.pobject
                        while pobj:
                            blender_mesh = pobj.build(builder, self)
                            if bone.isHidden:
                                blender_mesh.hide_render = True
                                blender_mesh.hide_set(True)
                            blender_mesh.parent = armature

                            # # Apply deformation and rigid transformations temporarily stored in the hsd_mesh
                            # # This is done here because the meshes are created before the object hierarchy exists
                            self.apply_bone_weights(blender_mesh, pobj, bone, armature)

                            # Remove degenerate geometry
                            # Most of the time it's generated from tristrips changing orientation (for example in a plane)
                            blender_mesh.data.validate(verbose=False, clean_customdata=False)
                            pobj = pobj.next
                        mesh = mesh.next

    def apply_bone_weights(self, mesh, hsd_mesh, hsd_bone, armature):
        #apply weights now that the bones actually exist

        bpy.context.view_layer.objects.active = mesh

        #TODO: this is inefficient, I should probably sort the vertices by the envelope index beforehand

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

    #This is needed for correctly applying all this envelope stuff
    def envelope_coord_system(hsd_joint):
        #r: Root
        #x: First parent bone
        #m: Referenced joint
        if hsd_joint.flags & hsd.JOBJ_SKELETON_ROOT: # r == x == m
            return None
        else:
            #find first parent bone
            hsd_x = find_skeleton(hsd_joint)
            x_inverse = get_hsd_invbind(hsd_joint)
            if hsd_x.id == hsd_joint.id: # r != x == m
                return x_inverse.inverted()
            elif hsd_x.flags & hsd.JOBJ_SKELETON_ROOT: # r == x != m
                return (hsd_x.temp_matrix).inverted() @ hsd_joint.temp_matrix
            else: # r != x != m
                return (hsd_x.temp_matrix @ x_inverse).inverted() @ hsd_joint.temp_matrix

    def get_hsd_invbind(hsd_joint):
        if hsd_joint.invbind:
            return Matrix(hsd_joint.invbind)
        else:
            if hsd_joint.temp_parent:
                return get_hsd_invbind(hsd_joint.temp_parent)
            else:
                identity = Matrix()
                identity.identity()
                return identity

    def find_skeleton(hsd_joint):
        while hsd_joint:
            if hsd_joint.flags & (JOBJ_SKELETON_ROOT | JOBJ_SKELETON):
                return hsd_joint
            hsd_joint = hsd_joint.temp_parent
        return None

    # def addConstraints(self, armature, bones):
    #     for hsd_joint in bones:
    #         if hsd_joint.flags & hsd.JOBJ_TYPE_MASK == hsd.JOBJ_EFFECTOR:
    #             if not hsd_joint.temp_parent:
    #                 notice_output("IK Effector has no Parent")
    #                 continue
    #             if hsd_joint.temp_parent.flags & hsd.JOBJ_TYPE_MASK == hsd.JOBJ_JOINT2:
    #                 chain_length = 3
    #                 pole_data_joint = hsd_joint.temp_parent.temp_parent
    #             elif hsd_joint.temp_parent.flags & hsd.JOBJ_TYPE_MASK == hsd.JOBJ_JOINT1:
    #                 chain_length = 2
    #                 pole_data_joint = hsd_joint.temp_parent
    #             target_robj = robj_get_by_type(hsd_joint, 0x10000000, 1)
    #             poletarget_robj = robj_get_by_type(pole_data_joint, 0x10000000, 0)
    #             length_robj = robj_get_by_type(hsd_joint.temp_parent, 0x40000000, 0)
    #             if not length_robj:
    #                 notice_output("No Pole angle and bone length constraint on IK Effector Parent")
    #                 continue
    #             bone_length = length_robj.val0
    #             pole_angle = length_robj.val1
    #             if length_robj.flags & 0x4:
    #                 pole_angle += math.pi #+180°
    #             #This is a hack needed due to how the IK systems differ
    #             #May break on models using a different exporter than the one used for XD/Colosseum
    #             #(Or just some inconveniently placed children)
    #             effector = armature.data.bones[hsd_joint.temp_name]
    #             effector_pos = Vector(effector.matrix_local.translation)
    #             effector_name = effector.name
    #             bpy.context.view_layer.objects.active = armature
    #             bpy.ops.object.mode_set(mode = 'EDIT')
    #             position = Vector(effector.parent.matrix_local.translation)
    #             direction = Vector(effector.parent.matrix_local.col[0][0:3]).normalized()
    #             direction *= bone_length * effector.parent.matrix_local.to_scale()[0]
    #             position += direction
    #             #XXX contrary to documentation, .translate() doesn't seem to exist on EditBones in 2.81
    #             #Swap this back when this gets fixed
    #             #armature.data.edit_bones[effector_name].translate(position - effector_pos)
    #             headpos = Vector(armature.data.edit_bones[effector_name].head[:]) + (position - effector_pos)
    #             armature.data.edit_bones[effector_name].head[:] = headpos[:]
    #             tailpos = Vector(armature.data.edit_bones[effector_name].tail[:]) + (position - effector_pos)
    #             armature.data.edit_bones[effector_name].tail[:] = tailpos[:]
    #             #
    #             """
    #             true_effector = effector
    #             distance = abs(effector.head.length - bone_length)
    #             for child in armature.data.bones[hsd_joint.temp_parent.temp_name].children:
    #                 l = abs(child.head.length - bone_length)
    #                 if l < distance:
    #                     true_effector = child
    #                     distance = l
    #             """
    #             bpy.ops.object.mode_set(mode = 'POSE')
    #             #if hsd_joint.temp_parent.flags & hsd.JOBJ_SKELETON:
    #             #adding the constraint

    #             c = armature.pose.bones[effector_name].constraints.new(type = 'IK')
    #             c.chain_count = chain_length
    #             if target_robj:
    #                 c.target = armature
    #                 c.subtarget = target_robj.u.temp_name
    #                 if poletarget_robj:
    #                     c.pole_target = armature
    #                     c.pole_subtarget = poletarget_robj.u.temp_name
    #                     c.pole_angle = pole_angle
    #             #else:
    #             #    notice_output("No Pos constraint RObj on IK Effector")
    #             #else:
    #             #    notice_output("Adding IK contraint to Bone without Bone parents has no effect")

    # def addInstances(self, armature, bones, mesh_dict):
    #     # TODO: this is broken, as far as I can tell this should copy hierarchy down from the instanced bone as well
    #     for bone in bones:
    #         if bone.flags & hsd.JOBJ_INSTANCE:
    #             child = bone.child
    #             dobj = child.u
    #             while dobj:
    #                 pobj = dobj.pobj
    #                 while pobj:
    #                     mesh = mesh_dict[pobj.id]
    #                     copy = mesh.copy()
    #                     copy.parent = armature
    #                     #copy.parent_bone = bone.temp_name
    #                     #correct_coordinate_orientation(copy)
    #                     copy.matrix_local = bone.temp_matrix
    #                     bpy.context.scene.collection.objects.link(copy)

    #                     pobj = pobj.next
    #                 dobj = dobj.next







