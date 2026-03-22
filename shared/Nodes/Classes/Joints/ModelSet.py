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
        base_name = os.path.basename(filepath)
        num_anims = len(self.animated_joints)
        pad = len(str(num_anims - 1)) if num_anims > 1 else 1
        actions = []

        for i, animated_joint in enumerate(self.animated_joints):
            # Use a placeholder name; renamed after build once we know the frame range
            action_name = '%s_Anim_%s' % (base_name, str(i).zfill(pad))
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

            # Rename to "Pose" if the action has at most one frame of animation
            frame_start, frame_end = action.frame_range
            if frame_end - frame_start <= 1:
                action.name = '%s_Pose_%s' % (base_name, str(i).zfill(pad))

            actions.append(action)

            bpy.ops.object.mode_set(mode='OBJECT')

        # Reset pose to rest position and select the first animation
        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode='POSE')
        for bone in armature.pose.bones:
            bone.location = (0, 0, 0)
            bone.rotation_euler = (0, 0, 0)
            bone.rotation_quaternion = (1, 0, 0, 0)
            bone.scale = (1, 1, 1)
        bpy.ops.object.mode_set(mode='OBJECT')

        first_anim = next((a for a in actions if '_Anim_' in a.name), None)
        if first_anim or actions:
            armature.animation_data.action = first_anim or actions[0]
        bpy.context.scene.frame_set(0)

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

        # Copy meshes for instanced bones (JOBJ_INSTANCE)
        self.addInstances(builder, armature, bones)

        self.addConstraints(armature, bones)

        bpy.context.view_layer.update()
        bpy.ops.object.mode_set(mode = 'OBJECT')

        return armature

    def translate_coordinate_system(self, obj):
        #correct orientation due to coordinate system differences
        obj.matrix_basis @= Matrix.Rotation(math.pi / 2, 4, [1.0,0.0,0.0])

    def addGeometry(self, builder, armature, bones):
        for bone in bones:
            if bone.flags & JOBJ_INSTANCE:
                pass  # Handled by addInstances() after all geometry is built

            else:
                if isinstance(bone.property, Mesh):
                    mesh = bone.property
                    mesh.build(builder, armature, bone)

    def addInstances(self, builder, armature, bones):
        """Copy mesh objects from instanced bones.

        JOBJ_INSTANCE bones reference another bone's geometry. After all normal
        geometry is built, we copy the referenced meshes and place them at the
        instance bone's transform. Matches legacy add_instances().
        """
        for bone in bones:
            if bone.flags & JOBJ_INSTANCE and bone.child:
                child = bone.child
                mesh = child.property
                if isinstance(mesh, Mesh):
                    while mesh:
                        pobj = mesh.pobject
                        while pobj:
                            original = builder.mesh_objects_by_pobj.get(pobj.address)
                            if original:
                                copy = original.copy()
                                copy.parent = armature
                                copy.matrix_local = bone.temp_matrix
                                bpy.context.scene.collection.objects.link(copy)
                            pobj = pobj.next
                        mesh = mesh.next

    def addConstraints(self, armature, bones):
        from .Joint import Joint
        from .BoneReference import BoneReference

        for hsd_joint in bones:
            joint_type = hsd_joint.flags & JOBJ_TYPE_MASK

            if joint_type == JOBJ_EFFECTOR:
                self._addIKConstraint(armature, hsd_joint, Joint, BoneReference)
            elif joint_type != JOBJ_JOINT2:
                self._addRegularConstraints(armature, hsd_joint, Joint)

    def _addIKConstraint(self, armature, hsd_joint, Joint, BoneReference):
        if not hsd_joint.temp_parent:
            return

        parent_type = hsd_joint.temp_parent.flags & JOBJ_TYPE_MASK
        if parent_type == JOBJ_JOINT2:
            chain_length = 3
            pole_data_joint = hsd_joint.temp_parent.temp_parent
        elif parent_type == JOBJ_JOINT1:
            chain_length = 2
            pole_data_joint = hsd_joint.temp_parent
        else:
            return

        target_robj = hsd_joint.getReferenceObject(Joint, 1)
        poletarget_robj = pole_data_joint.getReferenceObject(Joint, 3) if pole_data_joint else None
        effector_length_robj = hsd_joint.temp_parent.getReferenceObject(BoneReference, 0)
        joint2_length_robj = pole_data_joint.getReferenceObject(BoneReference, 0) if pole_data_joint else None
        if not effector_length_robj:
            return

        if joint2_length_robj:
            pole_angle = joint2_length_robj.property.pole_angle
        else:
            pole_angle = effector_length_robj.property.pole_angle

        # Enforce second bone length if present (3-bone IK chain)
        if chain_length == 3 and joint2_length_robj:
            joint1 = armature.data.bones[hsd_joint.temp_parent.temp_name]
            joint1_pos = Vector(joint1.matrix_local.translation)
            joint1_name = joint1.name
            bpy.context.view_layer.objects.active = armature
            bpy.ops.object.mode_set(mode='EDIT')
            position = Vector(joint1.parent.matrix_local.translation)
            direction = Vector(joint1.parent.matrix_local.col[0][0:3]).normalized()
            bone_length = joint2_length_robj.property.length
            direction *= bone_length * pole_data_joint.temp_matrix.to_scale()[0]
            position += direction

            offset = position - joint1_pos
            edit_bone = armature.data.edit_bones[joint1_name]
            edit_bone.head = Vector(edit_bone.head[:]) + offset
            edit_bone.tail = Vector(edit_bone.tail[:]) + offset
            bpy.ops.object.mode_set(mode='POSE')

        # Reposition the effector bone based on the IK bone length
        effector = armature.data.bones[hsd_joint.temp_name]
        effector_pos = Vector(effector.matrix_local.translation)
        effector_name = effector.name

        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode='EDIT')

        position = Vector(effector.parent.matrix_local.translation)
        direction = Vector(effector.parent.matrix_local.col[0][0:3]).normalized()
        bone_length = effector_length_robj.property.length
        direction *= bone_length * hsd_joint.temp_parent.temp_matrix.to_scale()[0]
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

    def _addRegularConstraints(self, armature, hsd_joint, Joint):
        """Add non-IK constraints from Reference objects (Copy Location, Track To, Copy Rotation, Limits)."""
        if not hsd_joint.reference:
            return

        copy_pos_refs = []
        dirup_x_ref = None
        orientation_ref = None
        limits = []

        reference = hsd_joint.reference
        while reference:
            if not (reference.flags & ROBJ_ACTIVE_BIT):
                reference = reference.next
                continue

            ref_type = reference.flags & ROBJ_TYPE_MASK

            if ref_type == REFTYPE_JOBJ and isinstance(reference.property, Joint):
                if reference.sub_type == 1:
                    copy_pos_refs.append(reference)
                elif reference.sub_type == 2:
                    dirup_x_ref = reference
                elif reference.sub_type == 4:
                    orientation_ref = reference

            elif ref_type == REFTYPE_LIMIT:
                constraint_type = reference.sub_type
                if 1 <= constraint_type <= 12:
                    limit_variable = ['rot', 'pos'][(constraint_type - 1) // (2 * 3)]
                    limit_component = ((constraint_type - 1) % 6) // 2
                    limit_direction = (constraint_type - 1) % 2  # 0: upper, 1: lower
                    limits.append((limit_variable, limit_component, limit_direction, reference.property))

            reference = reference.next

        if not (copy_pos_refs or dirup_x_ref or orientation_ref or limits):
            return

        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode='POSE')

        if copy_pos_refs:
            weight = 1.0 / len(copy_pos_refs)
            for ref in copy_pos_refs:
                c = armature.pose.bones[hsd_joint.temp_name].constraints.new(type='COPY_LOCATION')
                c.influence = weight
                c.target = armature
                c.subtarget = ref.property.temp_name

        if dirup_x_ref:
            c = armature.pose.bones[hsd_joint.temp_name].constraints.new(type='TRACK_TO')
            c.target = armature
            c.subtarget = dirup_x_ref.property.temp_name
            c.track_axis = 'TRACK_X'
            c.up_axis = 'UP_Y'

        if orientation_ref:
            c = armature.pose.bones[hsd_joint.temp_name].constraints.new(type='COPY_ROTATION')
            c.target = armature
            c.subtarget = orientation_ref.property.temp_name
            if hsd_joint.flags & 0x8:
                c.owner_space = 'LOCAL'
                c.target_space = 'LOCAL'

        for limit in limits:
            limit_type = {'pos': 'LIMIT_LOCATION', 'rot': 'LIMIT_ROTATION'}[limit[0]]
            existing_constraint = None
            for cnst in armature.pose.bones[hsd_joint.temp_name].constraints:
                if cnst.type == limit_type:
                    existing_constraint = cnst
            if not existing_constraint:
                existing_constraint = armature.pose.bones[hsd_joint.temp_name].constraints.new(type=limit_type)
                existing_constraint.owner_space = 'LOCAL_WITH_PARENT'

            axis = ['x', 'y', 'z'][limit[1]]
            limit_text = '%s_%s' % (['max', 'min'][limit[2]], axis)
            enable_text = 'use_' + limit_text
            if getattr(existing_constraint, enable_text):
                val = getattr(existing_constraint, limit_text)
                if limit[2] == 0:
                    val = max(val, limit[3])
                else:
                    val = min(val, limit[3])
                setattr(existing_constraint, limit_text, val)
            else:
                setattr(existing_constraint, enable_text, True)
                setattr(existing_constraint, limit_text, limit[3])







