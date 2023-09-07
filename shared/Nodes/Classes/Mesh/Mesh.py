import bpy
from mathutils import Matrix, Euler, Vector

from ...Node import Node
from ....Constants import *

# Mesh (aka DObject)
class Mesh(Node):
    class_name = "Mesh"
    fields = [
        ('name', 'string'),
        ('next', 'Mesh'),
        ('mobject', 'MaterialObject'),
        ('pobject', 'PObject')
    ]

    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)
        self.id = self.address

    def build(self, builder, armature, bone):

        material = self.mobject.build(builder)

        pobj = self.pobject
        while pobj:
            blender_mesh = pobj.build(builder)
            blender_mesh.data.materials.append(material)

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
    if hsd_joint.flags & JOBJ_SKELETON_ROOT: # r == x == m
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
    if hsd_joint.inverse_bind:
        return Matrix(hsd_joint.inverse_bind)
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