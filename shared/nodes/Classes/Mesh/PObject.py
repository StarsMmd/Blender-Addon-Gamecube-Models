import bpy
import struct

from ..Joints import *
from ..Shape import *
from ..Colors import *
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
        ('display_list_address', 'uint'),
        ('property', 'uint')
    ]
    display_list_chunk_size = 32

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

        self.display_list = parser.read_chunk(self.display_list_chunk_size * self.display_list_chunk_count, self.display_list_address)

        sources, face_lists, normals = self.read_geometry(parser)
        self.sources = sources
        self.face_lists = face_lists
        self.normals = normals

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

    def read_geometry(self, parser):
        vertices = self.vertex_list.vertices
        norm_dicts = []
        total_vertices_stride = 0
        for vertex in vertices:
            total_vertices_stride += vertex.stride
        #comp_frac = vertex.component_frac
        #TODO: add comp_frac to direct values

        sources = []
        facelists = []
        offset = 0

        # On the console the displaylist would be copied in a chunk, limit reading to that area
        size_limit = self.display_list_chunk_count * self.display_list_chunk_size

        for vertex_index, vertex in enumerate(vertices):
            faces = []
            norm_dict = {}
            norm_index = 0
            offset_in_chunk = 0

            opcode = struct.unpack('>B', self.display_list[offset_in_chunk: offset_in_chunk + 1])[0] & gx.GX_OPCODE_MASK
            while opcode != gx.GX_NOP and c < size_limit:
                offset_in_chunk += 1
                vertex_count = struct.unpack('>H', display_list[offset_in_chunk:offset_in_chunk + 2])[0]
                offset_in_chunk += 2

                indices = []
                for i in range(vertex_count):
                    index = struct.unpack(vertex_formats[vertex_index], display_list[c + offset:c + offset + descsizes[vertex_index]])
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
                opcode = struct.unpack('>B', display_list[offset_in_chunk:offset_in_chunk + 1])[0] & gx.GX_OPCODE_MASK

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






