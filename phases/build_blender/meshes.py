"""Build Blender mesh objects from IRModel.meshes."""
import bpy
from mathutils import Matrix, Vector

try:
    from ...shared.IR.enums import SkinType
except (ImportError, SystemError):
    from shared.IR.enums import SkinType


def build_meshes(ir_model, armature, context, options):
    """Create Blender meshes with materials, weights, and armature modifier.

    Args:
        ir_model: IRModel with meshes and bones populated.
        armature: The Blender armature object (from build_skeleton).
        context: Blender context.
        options: dict of importer options.
    """
    image_cache = {}
    for ir_mesh in ir_model.meshes:
        _build_mesh(ir_mesh, ir_model, armature, image_cache)


def _build_mesh(ir_mesh, ir_model, armature, image_cache):
    """Create a single Blender mesh object from an IRMesh."""
    # Create mesh data
    mesh_data = bpy.data.meshes.new('Mesh_' + ir_mesh.name)
    mesh_object = bpy.data.objects.new(ir_mesh.name, mesh_data)
    mesh_object.location = Vector((0, 0, 0))

    bpy.context.scene.collection.objects.link(mesh_object)

    # Create geometry
    mesh_data.from_pydata(ir_mesh.vertices, [], ir_mesh.faces)

    # UV layers
    for uv_layer in ir_mesh.uv_layers:
        bpy_uv = mesh_data.uv_layers.new(name=uv_layer.name)
        for i, (u, v) in enumerate(uv_layer.uvs):
            if i < len(bpy_uv.data):
                bpy_uv.data[i].uv = (u, v)

    # Color layers
    for color_layer in ir_mesh.color_layers:
        bpy_cl = mesh_data.vertex_colors.new(name=color_layer.name)
        for i, rgba in enumerate(color_layer.colors):
            if i < len(bpy_cl.data):
                bpy_cl.data[i].color = rgba

    # Normals
    if ir_mesh.normals:
        mesh_data.normals_split_custom_set(ir_mesh.normals)

    # Visibility
    if ir_mesh.is_hidden:
        mesh_object.hide_render = True
        mesh_object.hide_set(True)

    # Parent to armature
    mesh_object.parent = armature

    # Build material from IR
    if ir_mesh.material is not None:
        from .materials import build_material
        mat = build_material(ir_mesh.material, image_cache=image_cache)
    else:
        mat = bpy.data.materials.new(name=f'mat_{ir_mesh.name}')
    mesh_data.materials.append(mat)

    # Bone weights
    _apply_bone_weights(ir_mesh, ir_model, mesh_object, armature)

    # Finalize
    mesh_data.update(calc_edges=True, calc_edges_loose=False)
    mesh_data.validate(verbose=False, clean_customdata=False)


def _apply_bone_weights(ir_mesh, ir_model, mesh_object, armature):
    """Apply bone weights and armature modifier from IRBoneWeights."""
    bw = ir_mesh.bone_weights
    if bw is None:
        return

    if bw.type == SkinType.WEIGHTED and bw.assignments:
        # Create vertex groups for each bone referenced
        joint_groups = {}
        for vertex_idx, weight_list in bw.assignments:
            for bone_name, weight in weight_list:
                if bone_name not in joint_groups:
                    group = mesh_object.vertex_groups.new(name=bone_name)
                    joint_groups[bone_name] = group

        # Assign weights
        for vertex_idx, weight_list in bw.assignments:
            for bone_name, weight in weight_list:
                joint_groups[bone_name].add([vertex_idx], weight, 'REPLACE')

    elif bw.type == SkinType.SINGLE_BONE and bw.bone_name:
        group = mesh_object.vertex_groups.new(name=bw.bone_name)
        all_verts = [v.index for v in mesh_object.data.vertices]
        group.add(all_verts, 1.0, 'REPLACE')

    elif bw.type == SkinType.RIGID and bw.bone_name:
        # Rigid: attach all vertices to parent bone
        bone_idx = ir_mesh.parent_bone_index
        if bone_idx < len(ir_model.bones):
            bone_data = ir_model.bones[bone_idx]
            mesh_object.matrix_local = Matrix(bone_data.world_matrix)
        group = mesh_object.vertex_groups.new(name=bw.bone_name)
        all_verts = [v.index for v in mesh_object.data.vertices]
        group.add(all_verts, 1.0, 'REPLACE')

    # Armature modifier
    mod = mesh_object.modifiers.new('Skinmod', 'ARMATURE')
    mod.object = armature
    mod.use_bone_envelopes = False
    mod.use_vertex_groups = True
