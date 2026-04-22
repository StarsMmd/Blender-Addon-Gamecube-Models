"""Build Blender mesh objects from a BR model.

Pure bpy executor — geometry, UV/color layers, vertex groups, instance
copies, and parent-bone ownership all come pre-decided from the Plan phase.
Material node-graph construction is still invoked from IR here; it will
move into BR during the Plan-phase materials stage.
"""
import bpy
from mathutils import Matrix, Vector

try:
    from ....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def build_meshes(br_model, armature, context, logger=StubLogger()):
    """Create Blender meshes, vertex groups, armature modifiers, and instance
    copies from a BRModel. Returns a material_lookup dict keyed by mesh_key.

    Material node graphs are built on demand from BRMesh.material (still an
    IRMaterial until the materials stage lands); the result is cached by
    (material identity, cull flags) so duplicate meshes don't re-build.
    """
    image_cache = {}
    material_lookup = {}
    built_material_cache = {}  # {(id(material), cull_front, cull_back): bpy.types.Material}

    mesh_objects = []
    for i, br_mesh in enumerate(br_model.meshes):
        cached_mat = None
        if br_mesh.material is not None:
            cache_key = (id(br_mesh.material), br_mesh.material_cull_front, br_mesh.material_cull_back)
            cached_mat = built_material_cache.get(cache_key)

        mesh_obj, mat = _build_mesh(br_mesh, armature, image_cache, logger, i, cached_material=cached_mat)
        mesh_objects.append(mesh_obj)

        if mat:
            if br_mesh.material is not None:
                cache_key = (id(br_mesh.material), br_mesh.material_cull_front, br_mesh.material_cull_back)
                built_material_cache.setdefault(cache_key, mat)
            material_lookup[br_mesh.mesh_key] = mat
            logger.debug("  material_lookup['%s'] = '%s'", br_mesh.mesh_key, mat.name)

    instance_count = 0
    for instance in br_model.mesh_instances:
        original = mesh_objects[instance.source_mesh_index]
        copy = original.copy()
        copy.parent = armature
        copy.matrix_local = Matrix(instance.matrix_local)
        bpy.context.scene.collection.objects.link(copy)
        instance_count += 1

    logger.info("  Created %d mesh objects, %d instances, %d cached images",
                len(br_model.meshes), instance_count, len(image_cache))

    return material_lookup


def _build_mesh(br_mesh, armature, image_cache, logger, mesh_idx, cached_material=None):
    """Create one Blender mesh object from a BRMesh."""
    mesh_data = bpy.data.meshes.new(br_mesh.name)
    mesh_object = bpy.data.objects.new(br_mesh.name, mesh_data)
    mesh_object.location = Vector((0, 0, 0))

    bpy.context.scene.collection.objects.link(mesh_object)

    mesh_data.from_pydata(br_mesh.vertices, [], br_mesh.faces)

    for uv_layer in br_mesh.uv_layers:
        bpy_uv = mesh_data.uv_layers.new(name=uv_layer.name)
        for i, (u, v) in enumerate(uv_layer.uvs):
            if i < len(bpy_uv.data):
                bpy_uv.data[i].uv = (u, v)

    # FLOAT_COLOR so Blender doesn't auto-linearize — the IR stores sRGB
    # values matching the game's gamma-space rendering.
    for color_layer in br_mesh.color_layers:
        bpy_cl = mesh_data.color_attributes.new(
            name=color_layer.name, type='FLOAT_COLOR', domain='CORNER')
        for i, rgba in enumerate(color_layer.colors):
            if i < len(bpy_cl.data):
                bpy_cl.data[i].color = rgba

    # Blender 4.1+: flat polygons ignore custom split normals, so the
    # polygons must be marked smooth before per-loop normals take effect.
    if br_mesh.normals:
        for poly in mesh_data.polygons:
            poly.use_smooth = True
        mesh_data.normals_split_custom_set(br_mesh.normals)

    if br_mesh.is_hidden:
        mesh_object.hide_render = True
        mesh_object.hide_set(True)

    # Parent to the armature but record bone ownership via parent_bone
    # (no transform effect — the armature modifier drives deformation).
    mesh_object.parent = armature
    if br_mesh.parent_bone_name and br_mesh.parent_bone_name in armature.data.bones:
        mesh_object.parent_bone = br_mesh.parent_bone_name

    mat = _resolve_material(br_mesh, image_cache, logger, mesh_idx, cached_material)
    mesh_data.materials.append(mat)

    uv_names = [uv.name for uv in mesh_data.uv_layers]
    clr_names = [ca.name for ca in mesh_data.color_attributes]
    logger.debug("  mesh[%d] '%s': uv_layers=%s, color_attributes=%s, verts=%d, faces=%d",
                 mesh_idx, br_mesh.name, uv_names, clr_names,
                 len(mesh_data.vertices), len(mesh_data.polygons))

    _apply_vertex_groups(br_mesh.vertex_groups, mesh_object)
    _add_armature_modifier(mesh_object, armature)

    mesh_data.update(calc_edges=True, calc_edges_loose=False)
    mesh_data.validate(verbose=False, clean_customdata=False)

    return mesh_object, mat


def _resolve_material(br_mesh, image_cache, logger, mesh_idx, cached_material):
    """Fetch or build the Blender material for this mesh.

    BRMesh.material is still an IRMaterial pass-through (stage 4 will swap
    it for a BRMaterial); build_material() is invoked directly here.
    """
    if cached_material is not None:
        logger.debug("  mesh[%d] '%s': reusing material '%s'",
                     mesh_idx, br_mesh.name, cached_material.name)
        return cached_material

    if br_mesh.material is not None:
        from .materials import build_material
        mat = build_material(
            br_mesh.material,
            image_cache=image_cache,
            name=br_mesh.material_name,
            has_color_animation=br_mesh.has_color_animation,
        )
        logger.debug("  mesh[%d] '%s': material '%s' with %d textures",
                     mesh_idx, br_mesh.name, mat.name, len(br_mesh.material.texture_layers))
        # GameCube POBJ cull flags — CULL_BACK shows front faces, CULL_FRONT
        # shows back faces, both = invisible, neither = double-sided.
        if br_mesh.material_cull_front or br_mesh.material_cull_back:
            mat.use_backface_culling = True
        return mat

    mat = bpy.data.materials.new(name=br_mesh.material_name or 'placeholder_mat')
    logger.debug("  mesh[%d] '%s': placeholder material (no material)", mesh_idx, br_mesh.name)
    return mat


def _apply_vertex_groups(vertex_groups, mesh_object):
    """Create Blender vertex groups and assign weights from a BRVertexGroup list."""
    for vg in vertex_groups:
        group = mesh_object.vertex_groups.new(name=vg.name)
        for vertex_index, weight in vg.assignments:
            group.add([vertex_index], weight, 'REPLACE')


def _add_armature_modifier(mesh_object, armature):
    mod = mesh_object.modifiers.new('Skinmod', 'ARMATURE')
    mod.object = armature
    mod.use_bone_envelopes = False
    mod.use_vertex_groups = True
