import bpy

from ..Joints import *
from ..Shape import *
from ...Node import Node

from ....Constants import *


# PObject
class PObject(Node):
    class_name = "P Object"
    fields = [
        ('name', 'string'),
        ('next', 'PObject'),
        ('vertex_list', 'VertexList'),
        ('flags', 'ushort'),
        ('display_list_chunk_count', 'ushort'),
        ('display_list', 'uint'),
        ('property', 'uint')
    ]

    # Parse struct from binary file.
    def loadFromBinary(self, parser):
        super().loadFromBinary(parser)

        display_list_length = self.display_list_chunk_count * 32
        display_list_type = 'uchar[{count}]'.format(
            count = display_list_length
        )
        self.display_list = parser.read(display_list_type, self.display_list)

        if self.property > 0:
            property_type = self.flags & POBJ_TYPE_MASK
            if property_type == POBJ_SKIN:
                self.property = parser.read('Joint', self.property)
            elif property_type == POBJ_SHAPEANIM:
                self.property = parser.read('ShapeSet', self.property)
            else:
                self.property = parser.read('(*Envelope)[]', self.property)
        else:
            self.property = None

        self.blender_mesh = None

    def allocationSize(self):
        # If the property is an Envelope list then allocate space for
        # the list of pointers.
        size = super().allocationSize()
        if isinstance(self.property, list):
            size += len(self.property) * 4
        return size

    def allocationOffset(self):
        offset = super().allocationOffset()
        if isinstance(self.property, list):
            offset += len(self.property) * 4
        return offset

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        self.disp_list_count = disp_list.length
        if isinstance(self.property, Joint):
            self.flags = POBJ_SKIN
            self.property = self.property.address

        elif isinstance(self.property, ShapeSet):
            self.flags = POBJ_SHAPEANIM
            self.property = self.property.address
            
        else:
            self.flags = 0

        super().writeBinary(builder)


    def prepareForBlender(self, builder):
        super().prepareForBlender(builder)

        name = ''
        if self.name:
            name = self.name

        display_list = self.display_list
        vertex_list = self.vertex_list.vertices
        display_list_size = self.display_list_chunk_count

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

        if self.property:
            type = self.flags & POBJ_TYPE_MASK
            if type == POBJ_SHAPEANIM:
                shape_set = self.property
                self.make_shapeset(mesh_object, shape_set, normdicts[position_vertex_index])
                self.make_rigid_skin(self)
            elif type == POBJ_ENVELOPE:
                envelope_list = self.property
                envelope_vertex_index = None
                for index, vertex in enumerate(vertex_list):
                    if vertex.attribute == GX_VA_PNMTXIDX:
                        envelope_vertex_index = index
                if envelope_vertex_index != None:
                    self.make_deform_skin(self, envelope_list, sources[envelope_vertex_index], face_lists[envelope_vertex_index], faces)
                else:
                    raise InvalidEnvelopeError

            else:
                # Make skin
                # Deprecated, probably still used somewhere though
                joint = self.property
                self.make_skin(self, joint)

        else:
            self.make_rigid_skin(self)


        #mesh.calc_normals()
        self.normals = None
        for index, vertex in enumerate(vertex_list):
            if vertex.is_tex():
                uvlayer = self.make_texture_layer(mesh, vertex, sources[index], face_lists[index])
            elif vertex.attribute == GX_VA_NRM or vertex.attribute == GX_VA_NBT:
                self.assign_normals_to_mesh(self, mesh, vertex, sources[index], facelists[index])
                mesh.use_auto_smooth = True
            elif (vertex.attribute == GX_VA_CLR0 or
                  vertex.attribute == GX_VA_CLR1):
                self.add_color_layer(mesh, vertex, sources[index], face_lists[index])

        # Update mesh with new data
        # Remove degenerate faces (These mostly occur due to triangle strips creating invisible faces when changing orientation)
        mesh.update(calc_edges = True, calc_edges_loose = False)

        self.blender_mesh = mesh_object








