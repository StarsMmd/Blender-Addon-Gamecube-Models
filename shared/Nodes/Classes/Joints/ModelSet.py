import os
import bpy
import math
from mathutils import Matrix, Euler, Vector

from ..Mesh import *
from ..Misc.Spline import Spline
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
        armature = self._createArmature(builder)
        if armature is None:
            return

        if not self.animated_joints:
            return

        filepath = builder.options.get("filepath", "")
        for i, animated_joint in enumerate(self.animated_joints):
            action_name = os.path.basename(filepath) + '_Anim_' + str(i).zfill(2)
            action = bpy.data.actions.new(action_name)
            action.use_fake_user = True

            bpy.context.view_layer.objects.active = armature
            bpy.ops.object.mode_set(mode='POSE')
            for bone in armature.pose.bones:
                bone.rotation_mode = 'XYZ'
            for bone in armature.data.bones:
                bone.use_local_location = True

            armature.animation_data_create()
            armature.animation_data.action = action

            animated_joint.build(self.root_joint, action, armature, builder)

            bpy.ops.object.mode_set(mode='OBJECT')

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

        self.addConstraints(armature, bones)

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

    def addConstraints(self, armature, bones):
        from .Joint import Joint
        from .BoneReference import BoneReference

        for hsd_joint in bones:
            joint_type = hsd_joint.flags & JOBJ_TYPE_MASK
            if joint_type != JOBJ_EFFECTOR:
                continue
            if not hsd_joint.temp_parent:
                continue

            parent_type = hsd_joint.temp_parent.flags & JOBJ_TYPE_MASK
            if parent_type == JOBJ_JOINT2:
                chain_length = 3
                pole_data_joint = hsd_joint.temp_parent.temp_parent
            elif parent_type == JOBJ_JOINT1:
                chain_length = 2
                pole_data_joint = hsd_joint.temp_parent
            else:
                continue

            target_robj = hsd_joint.getReferenceObject(Joint, 1)
            poletarget_robj = pole_data_joint.getReferenceObject(Joint, 0) if pole_data_joint else None
            length_robj = hsd_joint.temp_parent.getReferenceObject(BoneReference, 0)
            if not length_robj:
                continue

            bone_length = length_robj.property.length
            pole_angle = length_robj.property.pole_angle

            # Reposition the effector bone based on the IK bone length
            effector = armature.data.bones[hsd_joint.temp_name]
            effector_pos = Vector(effector.matrix_local.translation)
            effector_name = effector.name

            bpy.context.view_layer.objects.active = armature
            bpy.ops.object.mode_set(mode='EDIT')

            position = Vector(effector.parent.matrix_local.translation)
            direction = Vector(effector.parent.matrix_local.col[0][0:3]).normalized()
            direction *= bone_length * effector.parent.matrix_local.to_scale()[0]
            position += direction

            offset = position - effector_pos
            edit_bone = armature.data.edit_bones[effector_name]
            edit_bone.head = Vector(edit_bone.head[:]) + offset
            edit_bone.tail = Vector(edit_bone.tail[:]) + offset

            bpy.ops.object.mode_set(mode='POSE')

            # Add IK constraint
            c = armature.pose.bones[effector_name].constraints.new(type='IK')
            c.chain_count = chain_length
            if target_robj:
                c.target = armature
                c.subtarget = target_robj.property.temp_name
                if poletarget_robj:
                    c.pole_target = armature
                    c.pole_subtarget = poletarget_robj.property.temp_name
                    c.pole_angle = pole_angle







