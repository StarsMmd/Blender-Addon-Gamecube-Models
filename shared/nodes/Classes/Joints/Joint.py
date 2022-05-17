import bpy
import math

from ...Node import Node
from ....Constants import *

# Joint (aka Bone)
class Joint(Node):
    class_name = "Joint"
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

        else:
            self.flags = 0
            self.property = self.property.address

        super().writeBinary(builder)

    def buildBoneHierarchy(self, builder, parent, hsd_parent):
        bones = []

        bpy.ops.object.mode_set(mode = 'EDIT')
        name = 'Bone_' + str(builder.bone_count)
        builder.bone_count += 1

        bone = armature_data.edit_bones.new(name = name)
        if builder.options.get("ik_hack"):
            bone.tail = Vector((0.0, 1e-3, 0.0))
        else:
            bone.tail = Vector((0.0, 1.0, 0.0))

        scale_x = Matrix.Scale(self.scale[0], 4, [1.0,0.0,0.0])
        scale_y = Matrix.Scale(self.scale[1], 4, [0.0,1.0,0.0])
        scale_z = Matrix.Scale(self.scale[2], 4, [0.0,0.0,1.0])
        rotation_x = Matrix.Rotation(self.rotation[0], 4, 'X')
        rotation_y = Matrix.Rotation(self.rotation[1], 4, 'Y')
        rotation_z = Matrix.Rotation(self.rotation[2], 4, 'Z')
        translation = Matrix.Translation(Vector(self.position))
        # Parent * T * R * S
        #bone_matrix = translation * rotation_z * rotation_y * rotation_x * scale_z * scale_y * scale_x
        bone_matrix = self.compileSRTMatrix(self.scale, self.rotation, self.position)
        #bone_matrix = Matrix()
        self.temp_matrix_local = bone_matrix
        if parent:
            bone_matrix = hsd_parent.temp_matrix @ bone_matrix
            bone.parent = parent
        bone.matrix = bone_matrix
        self.temp_matrix = bone_matrix
        self.temp_name = bone.name
        self.temp_parent = hsd_parent

        #bone.use_relative_parent = True
        if self.child and not self.flags & JOBJ_INSTANCE:
            bones += self.child.buildBoneHierarchy(builder, bone, hsd_bone)
        if self.next:
            bones += self.next.buildBoneHierarchy(builder, parent, hsd_parent)

        bones.append(self)
        return bones

    def compileSRTMatrix(self, scale, rotation, position):
        scale_x = Matrix.Scale(scale[0], 4, [1.0,0.0,0.0])
        scale_y = Matrix.Scale(scale[1], 4, [0.0,1.0,0.0])
        scale_z = Matrix.Scale(scale[2], 4, [0.0,0.0,1.0])
        rotation_x = Matrix.Rotation(rotation[0], 4, 'X')
        rotation_y = Matrix.Rotation(rotation[1], 4, 'Y')
        rotation_z = Matrix.Rotation(rotation[2], 4, 'Z')
        translation = Matrix.Translation(Vector(position))
        return translation @ rotation_z @ rotation_y @ rotation_x @ scale_z @ scale_y @ scale_x








