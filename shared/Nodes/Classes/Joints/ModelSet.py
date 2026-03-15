import os
import bpy
import math
from mathutils import Matrix, Euler, Vector

from ..Mesh import *
from ...Node import Node
from ....Constants import *
from ....BlenderVersion import BlenderVersion


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
            action_name = os.path.basename(filepath) + '_Anim_' + str(i)
            action = bpy.data.actions.new(action_name)
            action.use_fake_user = True

            # Action slots for Blender 4.4+
            if bpy.app.version >= BlenderVersion(4, 5, 0):
                action.slots.new('OBJECT', 'Armature')
                action.slots.active = action.slots[0]

            bpy.context.view_layer.objects.active = armature
            bpy.ops.object.mode_set(mode='POSE')
            for bone in armature.pose.bones:
                bone.rotation_mode = 'XYZ'
            for bone in armature.data.bones:
                bone.use_local_location = True

            armature.animation_data_create()
            armature.animation_data.action = action

            if bpy.app.version >= BlenderVersion(4, 4, 0):
                armature.animation_data.action_slot = action.slots[0]

            animated_joint.build(self.root_joint, action, builder, armature)

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

        # Add constraints (IK, copy location/rotation, track-to, limits)
        self.addConstraints(armature, bones)

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

    def addConstraints(self, armature, bones):
        from .BoneReference import BoneReference
        from .Joint import Joint

        for hsd_joint in bones:
            # IK effectors
            if hsd_joint.flags & JOBJ_TYPE_MASK == JOBJ_EFFECTOR:
                self._addIKConstraint(armature, hsd_joint)

            # Regular constraints from RObj linked list
            self._addReferenceConstraints(armature, hsd_joint)

    def _addIKConstraint(self, armature, hsd_joint):
        from .BoneReference import BoneReference
        from .Joint import Joint

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
        poletarget_robj = pole_data_joint.getReferenceObject(Joint, 0) if pole_data_joint else None
        length_robj = hsd_joint.temp_parent.getReferenceObject(BoneReference, 0)

        if not length_robj:
            return

        bone_length = length_robj.property.length
        pole_angle = length_robj.property.pole_angle

        # Enforce bone lengths by editing edit-bone positions
        effector = armature.data.bones[hsd_joint.temp_name]
        effector_pos = Vector(effector.matrix_local.translation)
        effector_name = effector.name

        bpy.context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode='EDIT')

        position = Vector(effector.parent.matrix_local.translation)
        direction = Vector(effector.parent.matrix_local.col[0][0:3]).normalized()
        direction *= bone_length * effector.parent.matrix_local.to_scale()[0]
        position += direction

        headpos = Vector(armature.data.edit_bones[effector_name].head[:]) + (position - effector_pos)
        armature.data.edit_bones[effector_name].head[:] = headpos[:]
        tailpos = Vector(armature.data.edit_bones[effector_name].tail[:]) + (position - effector_pos)
        armature.data.edit_bones[effector_name].tail[:] = tailpos[:]

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

    def _addReferenceConstraints(self, armature, hsd_joint):
        from .Joint import Joint

        reference = hsd_joint.reference
        while reference:
            if not (reference.flags & ROBJ_ACTIVE_BIT):
                reference = reference.next
                continue

            ref_type = reference.flags & ROBJ_TYPE_MASK
            sub_type = reference.flags & ROBJ_CNST_MASK

            if ref_type == REFTYPE_JOBJ and isinstance(reference.property, Joint):
                target_joint = reference.property
                bone_name = hsd_joint.temp_name
                target_name = target_joint.temp_name

                if sub_type == 1:
                    # COPY_LOCATION
                    c = armature.pose.bones[bone_name].constraints.new(type='COPY_LOCATION')
                    c.target = armature
                    c.subtarget = target_name

                elif sub_type == 2:
                    # TRACK_TO (X-axis)
                    c = armature.pose.bones[bone_name].constraints.new(type='TRACK_TO')
                    c.target = armature
                    c.subtarget = target_name
                    c.track_axis = 'TRACK_X'
                    c.up_axis = 'UP_Y'

                elif sub_type == 3:
                    # TRACK_TO (Y-axis, limited)
                    c = armature.pose.bones[bone_name].constraints.new(type='TRACK_TO')
                    c.target = armature
                    c.subtarget = target_name
                    c.track_axis = 'TRACK_Y'
                    c.up_axis = 'UP_Z'

                elif sub_type == 4:
                    # COPY_ROTATION
                    c = armature.pose.bones[bone_name].constraints.new(type='COPY_ROTATION')
                    c.target = armature
                    c.subtarget = target_name
                    if hsd_joint.flags & JOBJ_CLASSICAL_SCALING:
                        c.target_space = 'LOCAL'
                        c.owner_space = 'LOCAL'

            elif ref_type == REFTYPE_LIMIT:
                bone_name = hsd_joint.temp_name
                constraint_type = sub_type

                if 1 <= constraint_type <= 6:
                    # Rotation limits
                    c = armature.pose.bones[bone_name].constraints.new(type='LIMIT_ROTATION')
                    c.owner_space = 'LOCAL'
                    c.use_limit_x = constraint_type in (1, 2)
                    c.use_limit_y = constraint_type in (3, 4)
                    c.use_limit_z = constraint_type in (5, 6)

                elif 7 <= constraint_type <= 12:
                    # Position limits
                    c = armature.pose.bones[bone_name].constraints.new(type='LIMIT_LOCATION')
                    c.owner_space = 'LOCAL'
                    c.use_min_x = constraint_type in (7, 8)
                    c.use_max_x = constraint_type in (7, 8)
                    c.use_min_y = constraint_type in (9, 10)
                    c.use_max_y = constraint_type in (9, 10)
                    c.use_min_z = constraint_type in (11, 12)
                    c.use_max_z = constraint_type in (11, 12)

            reference = reference.next

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
