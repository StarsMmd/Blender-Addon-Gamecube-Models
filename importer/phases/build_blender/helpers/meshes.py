"""Build Blender mesh objects from IRModel.meshes."""
import bpy
from mathutils import Matrix, Vector

try:
    from .....shared.IR.enums import SkinType
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.enums import SkinType
    from shared.helpers.logger import StubLogger


def build_meshes(ir_model, armature, context, options, logger=StubLogger()):
    """Create Blender meshes with materials, weights, and armature modifier.

    Args:
        ir_model: IRModel with meshes and bones populated.
        armature: The Blender armature object (from build_skeleton).
        context: Blender context.
        options: dict of importer options.
        logger: Logger instance (defaults to StubLogger).
    """
    model_name = ir_model.name or "Model"
    image_cache = {}
    material_lookup = {}  # {mesh_name: bpy.types.Material} for material animations
    mesh_objects_by_bone = {}  # {bone_index: [mesh_objects]}
    for i, ir_mesh in enumerate(ir_model.meshes):
        mesh_obj, mat = _build_mesh(ir_mesh, ir_model, armature, image_cache, logger, i, model_name)
        if mesh_obj:
            bone_idx = ir_mesh.parent_bone_index
            mesh_objects_by_bone.setdefault(bone_idx, []).append(mesh_obj)
        if mat:
            bone_name = ir_model.bones[ir_mesh.parent_bone_index].name if ir_mesh.parent_bone_index < len(ir_model.bones) else 'unknown'
            material_lookup["mesh_%d_%s" % (i, bone_name)] = mat

    # Copy meshes for instance bones (JOBJ_INSTANCE)
    instance_count = 0
    for bone in ir_model.bones:
        if bone.instance_child_bone_index is not None:
            child_meshes = mesh_objects_by_bone.get(bone.instance_child_bone_index, [])
            for original in child_meshes:
                copy = original.copy()
                copy.parent = armature
                copy.matrix_local = Matrix(bone.world_matrix)
                bpy.context.scene.collection.objects.link(copy)
                instance_count += 1

    logger.info("  Created %d mesh objects, %d instances, %d cached images",
                len(ir_model.meshes), instance_count, len(image_cache))

    return material_lookup


def _build_mesh(ir_mesh, ir_model, armature, image_cache, logger, mesh_idx, model_name="Model"):
    """Create a single Blender mesh object from an IRMesh."""
    # Create mesh data
    mesh_name = '%s_mesh_%s' % (model_name, ir_mesh.name)
    mesh_data = bpy.data.meshes.new(mesh_name)
    mesh_object = bpy.data.objects.new(mesh_name, mesh_data)
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
        mat_name = '%s_mat_%d' % (model_name, mesh_idx)
        mat = build_material(ir_mesh.material, image_cache=image_cache, name=mat_name)
        logger.debug("  mesh[%d] '%s': material '%s' with %d textures",
                     mesh_idx, ir_mesh.name, mat.name, len(ir_mesh.material.texture_layers))
    else:
        mat = bpy.data.materials.new(name='%s_mat_%d' % (model_name, mesh_idx))
        logger.debug("  mesh[%d] '%s': placeholder material (no IR material)", mesh_idx, ir_mesh.name)
    mesh_data.materials.append(mat)

    # Log UV layer info
    uv_names = [uv.name for uv in mesh_data.uv_layers]
    clr_names = [vc.name for vc in mesh_data.vertex_colors]
    logger.debug("  mesh[%d] '%s': uv_layers=%s, vertex_colors=%s, verts=%d, faces=%d",
                 mesh_idx, ir_mesh.name, uv_names, clr_names,
                 len(mesh_data.vertices), len(mesh_data.polygons))

    # Bone weights
    _apply_bone_weights(ir_mesh, ir_model, mesh_object, armature, logger, mesh_idx)

    # Finalize
    mesh_data.update(calc_edges=True, calc_edges_loose=False)
    mesh_data.validate(verbose=False, clean_customdata=False)

    return mesh_object, mat


def _apply_bone_weights(ir_mesh, ir_model, mesh_object, armature, logger, mesh_idx):
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

        logger.debug("  mesh[%d] weights: WEIGHTED, %d assignments, %d groups: %s",
                     mesh_idx, len(bw.assignments), len(joint_groups), sorted(joint_groups.keys()))

    elif bw.type == SkinType.SINGLE_BONE and bw.bone_name:
        group = mesh_object.vertex_groups.new(name=bw.bone_name)
        all_verts = [v.index for v in mesh_object.data.vertices]
        group.add(all_verts, 1.0, 'REPLACE')
        logger.debug("  mesh[%d] weights: SINGLE_BONE '%s'", mesh_idx, bw.bone_name)

    elif bw.type == SkinType.RIGID and bw.bone_name:
        # Rigid: attach all vertices to parent bone
        bone_idx = ir_mesh.parent_bone_index
        if bone_idx < len(ir_model.bones):
            bone_data = ir_model.bones[bone_idx]
            mesh_object.matrix_local = Matrix(bone_data.world_matrix)
        group = mesh_object.vertex_groups.new(name=bw.bone_name)
        all_verts = [v.index for v in mesh_object.data.vertices]
        group.add(all_verts, 1.0, 'REPLACE')
        logger.debug("  mesh[%d] weights: RIGID '%s'", mesh_idx, bw.bone_name)

    # Armature modifier
    mod = mesh_object.modifiers.new('Skinmod', 'ARMATURE')
    mod.object = armature
    mod.use_bone_envelopes = False
    mod.use_vertex_groups = True
