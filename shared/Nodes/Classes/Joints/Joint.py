import bpy
import math
from mathutils import Matrix, Euler, Vector

from ...Node import Node
from ....Constants import *
from ..Rendering.Particle import Particle
from ..Misc.Spline import Spline


# Joint (aka Bone)
class Joint(Node):
    class_name = "Joint"
    isHidden = False
    fields = [
        ('name', 'string'),
        ('flags', 'uint'),
        ('child', 'Joint'),
        ('next', 'Joint'),
        ('property', 'uint'),
        ('rotation', 'vec3'),
        ('scale', 'vec3'),
        ('position', 'vec3'),
        ('inverse_bind', 'matrix'),
        ('reference', 'Reference')
    ]

    # Parse struct from binary file.
    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        self.id = self.address
        self.isHidden = self.flags & JOBJ_HIDDEN

        property_type = 'Mesh'
        if self.flags & JOBJ_PTCL:
            property_type = 'Particle'
        elif self.flags & JOBJ_SPLINE:
            property_type = 'Spline'

        if self.property > 0:
            self.property = parser.read(property_type, self.property)
        else:
            self.property = None

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        if isinstance(self.property, Particle):
            self.flags = JOBJ_PTCL
            self.property = self.property.address

        elif isinstance(self.property, Spline):
            self.flags = JOBJ_SPLINE
            self.property = self.property.address

        elif self.property is not None:
            self.flags = 0
            self.property = self.property.address

        else:
            self.flags = 0
            self.property = 0

        if self.isHidden:
            self.flags |= JOBJ_HIDDEN

        super().writeBinary(builder)

    def buildBoneHierarchy(self, builder, parent, hsd_parent, armature_data, root_parent=None):
        bones = []

        bpy.ops.object.mode_set(mode = 'EDIT')
        name = 'Bone_' + str(builder.bone_count)
        builder.bone_count += 1

        bone = armature_data.edit_bones.new(name = name)

        # Only apply small tail to effector and spline bones for IK hack
        if builder.options.get("ik_hack"):
            joint_type = self.flags & JOBJ_TYPE_MASK
            if joint_type == JOBJ_EFFECTOR or self.flags & JOBJ_SPLINE:
                tail_length = 1e-3
                if hsd_parent:
                    tail_length /= hsd_parent.scale[1]
                bone.tail = Vector((0.0, tail_length, 0.0))
            else:
                bone.tail = Vector((0.0, 1e-3, 0.0))
        else:
            bone.tail = Vector((0.0, 1.0, 0.0))

        # Track cumulative scale
        if hsd_parent:
            self.scl = [self.scale[i] * hsd_parent.scl[i] for i in range(3)]
        else:
            self.scl = list(self.scale)

        bone_matrix = self.compileSRTMatrix(self.scale, self.rotation, self.position)
        temp_matrix_local = bone_matrix
        self.temp_matrix_local = bone_matrix

        if hsd_parent:
            bone_matrix = hsd_parent.temp_matrix @ bone_matrix
            bone.parent = parent

        bone.matrix = bone_matrix
        self.temp_matrix = bone_matrix
        self.temp_name = bone.name
        self.temp_parent = hsd_parent

        # Compute per-bone edit matrices for scale correction
        self.edit_matrix = bone_matrix.normalized()
        if hsd_parent:
            self.local_edit_matrix = hsd_parent.edit_matrix.inverted() @ self.edit_matrix
            self.edit_scale_correction = hsd_parent.edit_scale_correction @ temp_matrix_local.normalized().inverted() @ temp_matrix_local
        else:
            self.local_edit_matrix = self.edit_matrix
            self.edit_scale_correction = temp_matrix_local.normalized().inverted() @ temp_matrix_local

        # Use aligned scale inheritance for proper scale handling
        bone.inherit_scale = 'ALIGNED'

        if self.child and not self.flags & JOBJ_INSTANCE:
            bones += self.child.buildBoneHierarchy(builder, bone, self, armature_data, root_parent)
        if self.next:
            bones += self.next.buildBoneHierarchy(builder, parent, hsd_parent, armature_data, root_parent)

        bones.append(self)
        return bones

    def compileSRTMatrix(self, scale, rotation, position, parent_scl=None):
        scale_x = Matrix.Scale(scale[0], 4, [1.0,0.0,0.0])
        scale_y = Matrix.Scale(scale[1], 4, [0.0,1.0,0.0])
        scale_z = Matrix.Scale(scale[2], 4, [0.0,0.0,1.0])
        rotation_x = Matrix.Rotation(rotation[0], 4, 'X')
        rotation_y = Matrix.Rotation(rotation[1], 4, 'Y')
        rotation_z = Matrix.Rotation(rotation[2], 4, 'Z')
        translation = Matrix.Translation(Vector(position))
        mtx = translation @ rotation_z @ rotation_y @ rotation_x @ scale_z @ scale_y @ scale_x

        # Apply scale correction when parent scale is provided
        if parent_scl is not None:
            for i in range(3):
                for j in range(3):
                    if parent_scl[i] != 0:
                        mtx[i][j] *= parent_scl[j] / parent_scl[i]

        return mtx


    def getReferenceObject(self, type, sub_type):
        reference = self.reference
        while reference:
            if isinstance(reference.property, type) and reference.sub_type == sub_type:
                return reference
            reference = reference.next

        return None
