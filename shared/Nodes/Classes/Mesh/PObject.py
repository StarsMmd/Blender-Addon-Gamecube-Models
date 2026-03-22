import bpy
import struct
from mathutils import Matrix, Euler, Vector

from ..Joints import *
from ..Shape import *
from ..Colors import *
from ...Node import Node

from ....Constants import *
from ....BlenderVersion import BlenderVersion
from ....Errors import *


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

        # Log key fields for debugging UV/vertex issues
        vtx_descs = []
        for v in self.vertex_list.vertices:
            vtx_descs.append('attr=%d type=%d bp=0x%X stride=%d frac=%d' %
                             (v.attribute, v.attribute_type, v.base_pointer, v.stride, v.component_frac))
        parser.logger.debug("PObject 0x%X: dl_addr=0x%X dl_chunks=%d vtxlist=0x%X descs=[%s]",
                            self.address, self.display_list_address, self.display_list_chunk_count,
                            self.vertex_list.address, ', '.join(vtx_descs))

        if self.property > 0:
            property_type = self.flags & POBJ_TYPE_MASK
            if property_type == POBJ_SKIN:
                parser.logger.debug("PObject 0x%X: property -> Joint (SKIN) at 0x%X", self.address, self.property)
                self.property = parser.read('Joint', self.property)
            elif property_type == POBJ_SHAPEANIM:
                parser.logger.debug("PObject 0x%X: property -> ShapeSet (SHAPEANIM) at 0x%X", self.address, self.property)
                self.property = parser.read('ShapeSet', self.property)
            else:
                parser.logger.debug("PObject 0x%X: property -> EnvelopeList[] (ENVELOPE) at 0x%X", self.address, self.property)
                self.property = parser.read('(*EnvelopeList)[]', self.property)
        else:
            self.property = None

        sources, face_lists, normals = self.read_geometry(parser)
        self.sources = sources
        self.face_lists = face_lists
        self.normals = normals

    def allocationSize(self):
        # If the property is an Envelope list then allocate space for
        # the null-terminated list of pointers that precedes the node.
        size = super().allocationSize()
        if isinstance(self.property, list):
            size += (len(self.property) + 1) * 4  # +1 for null terminator
        return size

    def allocationOffset(self):
        offset = super().allocationOffset()
        if isinstance(self.property, list):
            offset += (len(self.property) + 1) * 4  # +1 for null terminator
        return offset

    # Tells the builder how to write this node's data to the binary file.
    # Returns the offset the builder was at before it started writing its own data.
    def writeBinary(self, builder):
        # TODO: properly calculate size of display list chunks
        # TODO: make sure display list chunks are written and field is replaced with pointer to data
        # TODO: self.disp_list_count = ...
        if isinstance(self.property, Joint):
            self.flags = POBJ_SKIN
            self.property = self.property.address

        elif isinstance(self.property, ShapeSet):
            self.flags = POBJ_SHAPEANIM
            self.property = self.property.address
            
        elif isinstance(self.property, list):
            # Envelope list — write array of pointers before the node data
            # The pointer array was pre-allocated in allocationOffset
            array_address = self.address - self.allocationOffset()
            for i, envelope in enumerate(self.property):
                addr = envelope.address if envelope is not None and envelope.address is not None else 0
                builder.write(addr, 'uint', array_address + i * 4, relative_to_header=True)
                if addr != 0:
                    builder.relocations.append(array_address + i * 4)
            # Null terminator
            builder.write(0, 'uint', array_address + len(self.property) * 4, relative_to_header=True)
            self.property = array_address
            self.flags = 0

        else:
            self.flags = 0
            self.property = 0

        super().writeBinary(builder)


    def build(self, builder):

        name = ''
        if self.name:
            name = self.name
        else:
            name = str(builder.mesh_count)
        builder.mesh_count += 1

        vertex_list = self.vertex_list.vertices

        # Log vertex descriptors for this PObject
        attr_names = {GX_VA_PNMTXIDX: 'PNMTXIDX', GX_VA_POS: 'POS', GX_VA_NRM: 'NRM',
                      GX_VA_NBT: 'NBT', GX_VA_CLR0: 'CLR0', GX_VA_CLR1: 'CLR1'}
        clr_type_names = {gx.GX_RGBA8: 'RGBA8', gx.GX_RGBA6: 'RGBA6', gx.GX_RGBA4: 'RGBA4',
                          gx.GX_RGBX8: 'RGBX8', gx.GX_RGB8: 'RGB8', gx.GX_RGB565: 'RGB565'}
        descs = []
        for v in vertex_list:
            if v.attribute in attr_names:
                desc = attr_names[v.attribute]
                if v.attribute in (GX_VA_CLR0, GX_VA_CLR1):
                    desc += '(%s)' % clr_type_names.get(v.component_type, 'type_%d' % v.component_type)
                descs.append(desc)
            elif v.isTexture():
                descs.append('TEX%d' % (v.attribute - gx.GX_VA_TEX0))
            else:
                descs.append('attr_%d' % v.attribute)
        builder.logger.debug('  PObj 0x%X: vertex descriptors = [%s]', self.address, ', '.join(descs))

        position_vertex_index = None #index of the vtxdesc that holds vertex position data
        for i in range(len(vertex_list)):
            vertex = vertex_list[i]
            if vertex.attribute == GX_VA_POS:
                position_vertex_index = i

        if position_vertex_index == None:
            raise MeshWithoutPositionError

        #TODO: move the loop here to avoid redundancy
        vertices = self.sources[position_vertex_index]
        faces = self.face_lists[position_vertex_index]

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
                self.make_shapeset(builder, mesh_object, shape_set, self.normals[position_vertex_index])
                self.make_rigid_skin()
            elif type == POBJ_ENVELOPE:
                envelope_list = self.property
                envelope_vertex_index = None
                for index, vertex in enumerate(vertex_list):
                    if vertex.attribute == GX_VA_PNMTXIDX:
                        envelope_vertex_index = index
                if envelope_vertex_index != None:
                    self.make_deform_skin(envelope_list, self.sources[envelope_vertex_index], self.face_lists[envelope_vertex_index], faces)
                else:
                    raise InvalidEnvelopeError

            else:
                # Make skin
                # Deprecated, probably still used somewhere though
                joint = self.property
                self.make_skin(joint)

        else:
            self.make_rigid_skin()


        #mesh.calc_normals()
        self.normals = None
        for index, vertex in enumerate(vertex_list):
            if vertex.isTexture():
                uvlayer = self.make_texture_layer(mesh, vertex, self.sources[index], self.face_lists[index])
            elif vertex.attribute == GX_VA_NRM or vertex.attribute == GX_VA_NBT:
                self.assign_normals_to_mesh(mesh, vertex, self.sources[index], self.face_lists[index])
                # use_auto_smooth removed in Blender 4.1
                if bpy.app.version < BlenderVersion(4, 1, 0):
                    mesh.use_auto_smooth = True
            elif (vertex.attribute == GX_VA_CLR0 or
                  vertex.attribute == GX_VA_CLR1):
                self.add_color_layer(mesh, vertex, self.sources[index], self.face_lists[index])

        # Log UV and color layers created on this mesh
        uv_names = [uv.name for uv in mesh.uv_layers]
        clr_names = [vc.name for vc in mesh.vertex_colors]
        builder.logger.debug('  PObj 0x%X mesh "%s": uv_layers=%s, vertex_colors=%s',
                             self.address, mesh.name, uv_names, clr_names)

        # Log UV coordinate ranges for each UV layer
        for uv_layer in mesh.uv_layers:
            us = [d.uv[0] for d in uv_layer.data]
            vs = [d.uv[1] for d in uv_layer.data]
            if us:
                builder.logger.debug('  PObj 0x%X UV "%s" range: U=[%.3f, %.3f] V=[%.3f, %.3f]',
                                     self.address, uv_layer.name, min(us), max(us), min(vs), max(vs))

        # Log vertex alpha statistics for alpha_0 layer (if it has CLR0 data)
        if 'alpha_0' in mesh.vertex_colors:
            alphas = [d.color[0] for d in mesh.vertex_colors['alpha_0'].data]
            if alphas:
                unique_a = set(round(a, 4) for a in alphas)
                builder.logger.debug('  PObj 0x%X alpha_0 stats: min=%.4f max=%.4f unique=%d sample=%s',
                                     self.address, min(alphas), max(alphas), len(unique_a),
                                     sorted(unique_a)[:10])

        # On the GameCube, when CLR0 isn't in the vertex format the GX hardware
        # uses a default color register (white / full alpha).  Create default
        # color_0 and alpha_0 vertex-color layers so that ShaderNodeAttribute
        # nodes referencing these names return 1.0 instead of 0.0.
        if 'color_0' not in mesh.vertex_colors:
            color_layer = mesh.vertex_colors.new(name='color_0')
            for i in range(len(color_layer.data)):
                color_layer.data[i].color = [1.0, 1.0, 1.0, 1.0]
        if 'alpha_0' not in mesh.vertex_colors:
            alpha_layer = mesh.vertex_colors.new(name='alpha_0')
            for i in range(len(alpha_layer.data)):
                alpha_layer.data[i].color = [1.0, 1.0, 1.0, 1.0]

        # Update mesh with new data
        # Remove degenerate faces (These mostly occur due to triangle strips creating invisible faces when changing orientation)
        mesh.update(calc_edges = True, calc_edges_loose = False)
        self.blender_mesh = mesh

        return mesh_object

    def read_geometry(self, parser):
        vertices = self.vertex_list.vertices
        normal_dicts = []
        stride = 0
        for vertex in vertices:
            stride += parser.getTypeLength(vertex.getFormat())
        #comp_frac = vertex.component_frac
        #TODO: add comp_frac to direct values

        sources = []
        face_lists = []

        # On the console the displaylist would be copied in a chunk, limit reading to that area
        display_list_size = self.display_list_chunk_count * self.display_list_chunk_size
        offset_in_vertex_list = 0
        
        for vertex_index, vertex in enumerate(vertices):
            vertex_format = vertex.getFormat()
            faces = []
            norm_dict = {}
            norm_index = 0
            offset = 0

            opcode = parser.read('uchar', self.display_list_address, offset)  & gx.GX_OPCODE_MASK
            offset += parser.getTypeLength('uchar')

            while opcode != gx.GX_NOP and offset < display_list_size:
                vertex_count = parser.read('ushort', self.display_list_address, offset)
                offset += parser.getTypeLength('ushort')

                indices = []
                for i in range(vertex_count):
                    index = parser.read(vertex.getFormat(), self.display_list_address, offset + offset_in_vertex_list)
                    if vertex.attribute_type == gx.GX_DIRECT:
                        indices.append(index)
                    else:
                        if not index in norm_dict.keys():
                            norm_dict[index] = norm_index
                            norm_index += 1
                        indices.append(norm_dict[index])
                    
                    offset += stride

                if opcode == gx.GX_DRAW_QUADS:
                    for i in range(vertex_count // 4):
                        idx = i * 4
                        face = [indices[idx + 3],
                                indices[idx + 2],
                                indices[idx + 1],
                                indices[idx + 0]]
                        faces.append(face)
                elif opcode == gx.GX_DRAW_TRIANGLES:
                    for i in range(vertex_count // 3):
                        idx = i * 3
                        face = [indices[idx + 0],
                                indices[idx + 2],
                                indices[idx + 1]]
                        faces.append(face)
                elif opcode == gx.GX_DRAW_TRIANGLE_STRIP:
                    for i in range(vertex_count - 2):
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
                    for i in range(vertex_count - 2):
                        idx = i + 1
                        face = [first_index,
                                indices[idx + 1],
                                indices[idx]]
                        #latest_index = indices[idx]
                        faces.append(face)
                elif opcode == gx.GX_DRAW_LINES:
                    parser.logger.warning("GX_DRAW_LINES not supported, skipped")
                elif opcode == gx.GX_DRAW_LINE_STRIP:
                    parser.logger.warning("GX_DRAW_LINE_STRIP not supported, skipped")
                elif opcode == gx.GX_DRAW_POINTS:
                    parser.logger.warning("GX_DRAW_POINTS not supported, skipped")
                else:
                    parser.logger.warning("Unsupported geometry primitive opcode 0x%X, skipped", opcode)

                opcode = parser.read('uchar', self.display_list_address, offset)  & gx.GX_OPCODE_MASK
                offset += parser.getTypeLength('uchar')

            vertices = []
            if vertex.attribute_type == gx.GX_DIRECT:
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
                vertices = self.read_vertex_data(parser, vertex, indices)

            sources.append(vertices)
            face_lists.append(faces)
            normal_dicts.append(norm_dict)
            offset_in_vertex_list += parser.getTypeLength(vertex.getFormat())

        return sources, face_lists, normal_dicts

    def read_vertex_data(self, parser, vertex, indices):
        #TODO: add support for NBT
        data = []
        base_pointer = vertex.base_pointer
        vertex_format = vertex.getDirectElementType()
        format_length = parser.getTypeLength(vertex_format)
        if vertex.attribute == gx.GX_VA_NBT and vertex.component_count == gx.GX_NRM_NBT3:
            #Normal, Binormal and Tangent are individually indexed
            for index in indices:
                value = []
                for i in range(3):
                    position = vertex.stride * index[i] + i * format_length
                    value[i*3:i*3+3] = parser.read(vertex_format, base_pointer, position)
                if vertex.attribute_type != gx.GX_F32:
                    value = [v / (1 << vertex.component_frac) for v in value]
                data.append(value)
        else:
            for index in indices:
                position = vertex.stride * index
                value = parser.read(vertex_format, base_pointer, position)
                if not (vertex.isMatrix()
                        or vertex.attribute == gx.GX_VA_CLR0
                        or vertex.attribute == gx.GX_VA_CLR1
                        or vertex.attribute_type == gx.GX_F32):
                    value = [v / (1 << vertex.component_frac) for v in value]

                data.append(value)
        return data

    def make_deform_skin(self, envelope_list, source, faces, g_faces):
        #temporarily store vertex group info in the hsd object
        #envelope indices can only be GX_DIRECT

        indices = {}
        for j, face in enumerate(g_faces):
            for i, vertex in enumerate(face):
                indices[vertex] = source[faces[j][i]] // 3 # see GXPosNrmMtx
        indices = list(indices.items())

        #HSD envelopes do *NOT* correspond to Blender's envelope setting for skinning
        envelopes = []
        for envelope in envelope_list:
            envelopes.append([(entry.weight, entry.joint) for entry in envelope.envelopes])

        self.skin = (indices, envelopes)

    def make_skin(self, joint):
        self.skin = (None, joint.id)

    def make_rigid_skin(self):
        self.skin = (None, None)

    def make_shapeset(self, builder, ob, shape_set, normdict):
        #ob.shape_key_add(from_mix = False)
        #TODO: implement normals
        for shape_index in range(shape_set.shape_count + 1):
            shapekey = ob.shape_key_add(from_mix = False)
            vertex_list = shape_set.vertex_set[shape_index]

            for tri_index in range(shape_set.vertex_tri_count):
                value = vertex_list[tri_index]
                shapekey.data[normdict[tri_index]].co = value

    def assign_normals_to_mesh(self, meshdata, vertex, source, faces):
        #temporarily store normals in pobj to then be applied when bone deformations are done
        normals = [None] * len(meshdata.loops)
        for polygon in meshdata.polygons:
            face = faces[polygon.index]
            range = polygon.loop_indices
            minr = min(range)

            if vertex.attribute == GX_VA_NBT:
                for i in range:
                    n = source[face[i - minr]][0:3]
                    v = Vector(n)
                    if v.length > 0:
                        v.normalize()
                    normals[i] = v[:]
            else:
                for i in range:
                    n = source[face[i - minr]]
                    v = Vector(n)
                    if v.length > 0:
                        v.normalize()
                    normals[i] = v[:]
        self.normals = normals

    @staticmethod
    def _linearize_component(c):
        return c / 12.92 if c <= 0.0404482362771082 else pow((c + 0.055) / 1.055, 2.4)

    def add_color_layer(self, meshdata, vertex, source, faces):
        if vertex.attribute == gx.GX_VA_CLR0:
            color_num = '0'
        elif vertex.attribute == gx.GX_VA_CLR1:
            color_num = '1'
        color_layer = meshdata.vertex_colors.new(name = 'color_' + color_num)
        alpha_layer = meshdata.vertex_colors.new(name = 'alpha_' + color_num)
        for polygon in meshdata.polygons:
            face = faces[polygon.index]
            range = polygon.loop_indices
            minr = min(range)

            for i in range:
                color = source[face[i - minr]]
                r = color.red / 255
                g = color.green / 255
                b = color.blue / 255
                a = color.alpha / 255
                color_layer.data[i].color = [r, g, b, a]
                alpha_layer.data[i].color = [a, a, a, 1.0]

    def make_texture_layer(self, meshdata, vertex, source, faces):
        uvtex = meshdata.uv_layers.new()
        uvtex.name = 'uvtex_' + str(vertex.attribute - gx.GX_VA_TEX0)
        uvlayer = meshdata.uv_layers[uvtex.name]
        for polygon in meshdata.polygons:
            face = faces[polygon.index]
            range = polygon.loop_indices
            minr = min(range)

            for i in range:
                coords = source[face[i - minr]]
                #blender's UV coordinate origin is in the bottom left for some reason
                uvlayer.data[i].uv = [coords[0], 1 - coords[1]]
        return uvtex
