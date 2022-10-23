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

        current_offset = self.display_list
        for i in range(self.display_list_chunk_count):
            next_chunk_offset = current_offset + 32
            while current_offset < next_chunk_offset:

                current_offset = next_chunk_offset

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
        # TODO: properly calculate size of display list chunks
        # TODO: make sure display list chunks are written and field is replaced with pointer to data
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
        else:
            name = str(builder.mesh_count)

        builder.mesh_count += 1

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
        sources, face_lists, normals = self.read_geometry()
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
                self.make_shapeset(mesh_object, shape_set, normals[position_vertex_index])
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
            if vertex.isTexture():
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

    def read_geometry(displist, displistsize):
        vertices = self.vertex_list.vertices
        vertex_formats = []
        descsizes = []
        normdicts= []
        stride = 0
        for vertex in vertices:
            fmt = get_vtxdesc_element_fmt(vertex)
            vertex_formats.append(fmt)
            size = struct.calcsize(fmt)
            descsizes.append(size)
            stride += size
        #comp_frac = vertex.component_frac
        #TODO: add comp_frac to direct values

        sources = []
        facelists = []
        offset = 0
        for vertex_index, vertex in enumerate(vertices):
            faces = []
            norm_dict = {}
            norm_index = 0
            c = 0
            opcode = displist[c] & gx.GX_OPCODE_MASK
            #On the console the displaylist would be copied in a chunk, limit reading to that area
            size_limit = displistsize * 0x20
            while opcode != gx.GX_NOP and c < size_limit:
                c += 1
                vtxcount = struct.unpack('>H', displist[c:c + 2])[0]
                c += 2

                indices = []
                for i in range(vtxcount):
                    index = struct.unpack(vertex_formats[vertex_index], displist[c + offset:c + offset + descsizes[vertex_index]])
                    if not len(index) > 1:
                        index = index[0]
                    else:
                        index = list(index)
                    indices.append(index)
                    c += stride

                if not vertex.attr_type == gx.GX_DIRECT:
                    i = 0
                    for index in indices:
                        if not index in norm_dict.keys():
                            norm_dict[index] = norm_index
                            norm_index += 1
                        indices[i] = norm_dict[index]
                        i += 1

                if opcode == gx.GX_DRAW_QUADS:
                    for i in range(vtxcount // 4):
                        idx = i * 4
                        face = [indices[idx + 3],
                                indices[idx + 2],
                                indices[idx + 1],
                                indices[idx + 0]]
                        faces.append(face)
                elif opcode == gx.GX_DRAW_TRIANGLES:
                    for i in range(vtxcount // 3):
                        idx = i * 3
                        face = [indices[idx + 0],
                                indices[idx + 2],
                                indices[idx + 1]]
                        faces.append(face)
                elif opcode == gx.GX_DRAW_TRIANGLE_STRIP:
                    for i in range(vtxcount - 2):
                        if i % 2 == 0:
                            face = [indices[i + 1],
                                    indices[i + 0],
                                    indices[i + 2]]
                        else:
                            face = [indices[i + 0],
                                    indices[i + 1],
                                    indices[i + 2]]
                        faces.append(face)
                elif opcode == gx.GX_DRAW_TRIANGLE_FAN:
                    first_index = indices[0]
                    #latest_index = indices[1]
                    for i in range(vtxcount - 2):
                        idx = i + 1
                        face = [first_index,
                                indices[idx + 1],
                                indices[idx]]
                        #latest_index = indices[idx]
                        faces.append(face)
                elif opcode == gx.GX_DRAW_LINES:
                    notice_output("GX_DRAW_LINES not supported, skipped")
                elif opcode == gx.GX_DRAW_LINE_STRIP:
                    notice_output("GX_DRAW_LINE_STRIP not supported, skipped")
                elif opcode == gx.GX_DRAW_POINTS:
                    notice_output("GX_DRAW_POINTS not supported, skipped")
                else:
                    notice_output("Unsupported geometry primitive, skipped")
                opcode = displist[c] & gx.GX_OPCODE_MASK

            vertices = []
            if vertex.attr_type == gx.GX_DIRECT:
                #this means the indices are actually the raw data they would be indexing
                i = 0
                new_faces = []
                for face in faces:
                    new_face = []
                    for f in face:
                        vertices.append(f)
                        new_face.append(i)
                        i += 1
                    new_faces.append(new_face)
                faces = new_faces
            else:
                indices = []
                norm_indices = []
                for key, value in norm_dict.items():
                    indices.append(key)
                    norm_indices.append(value)
                indices = [x for _,x in sorted(zip(norm_indices,indices))]
                vertices = read_vertex_data(vertex, indices)

            sources.append(vertices)
            facelists.append(faces)
            normdicts.append(norm_dict)
            offset += descsizes[vertex_index]

        return sources, facelists, normdicts






