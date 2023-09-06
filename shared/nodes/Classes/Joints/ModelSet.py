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
        bones = self.root_joint.buildBoneHierarchy(builder, None, None, armature_data)

        bpy.ops.object.mode_set(mode = 'POSE')

        # Add meshes
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
                    mesh.build(builder, armature, bone)

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







