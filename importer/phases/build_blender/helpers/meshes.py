"""Build Blender mesh objects from a BR model.

Pure bpy executor — geometry, UV/color layers, vertex groups, instance
copies, parent-bone ownership, and material node graphs all come
pre-decided from the Plan phase.
"""
import bpy
from mathutils import Matrix, Vector

try:
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.helpers.logger import StubLogger


def build_meshes(br_model, armature, context, logger=StubLogger()):
    """Create Blender meshes, vertex groups, armature modifiers, and instance
    copies from a BRModel. Materials are built once per ``BRModel.materials``
    entry and reused across every BRMesh that references the same
    ``material_index``.

    In: br_model (BRModel); armature (bpy.types.Object);
        context (Blender context); logger (Logger).
    Out: dict[str, bpy.types.Material] — mesh_key → material, consumed later
         by the animation baker to bind material-animation fcurves.
    """
    image_cache = {}
    material_lookup = {}

    from .materials import build_material
    bpy_materials = [
        build_material(br_material, image_cache=image_cache)
        for br_material in br_model.materials
    ]

    mesh_objects = []
    for i, br_mesh in enumerate(br_model.meshes):
        mat = bpy_materials[br_mesh.material_index] if br_mesh.material_index is not None else None
        mesh_obj = _build_mesh(br_mesh, armature, logger, i, material=mat)
        mesh_objects.append(mesh_obj)

        if mat is not None:
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

    logger.info("  Created %d mesh objects, %d instances, %d cached images, %d materials",
                len(br_model.meshes), instance_count, len(image_cache), len(bpy_materials))

    return material_lookup


def _build_mesh(br_mesh, armature, logger, mesh_idx, material=None):
    """Create one Blender mesh object from a BRMesh.

    In: br_mesh (BRMesh); armature (bpy.types.Object);
        logger (Logger); mesh_idx (int, for debug logs);
        material (bpy.types.Material|None, falls back to an empty placeholder).
    Out: bpy.types.Object — the newly created mesh object, linked to the scene.
    """
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

    if material is None:
        material = bpy.data.materials.new(name=br_mesh.name + '_mat')
        logger.debug("  mesh[%d] '%s': placeholder material", mesh_idx, br_mesh.name)
    mesh_data.materials.append(material)

    uv_names = [uv.name for uv in mesh_data.uv_layers]
    clr_names = [ca.name for ca in mesh_data.color_attributes]
    logger.debug("  mesh[%d] '%s': uv_layers=%s, color_attributes=%s, verts=%d, faces=%d",
                 mesh_idx, br_mesh.name, uv_names, clr_names,
                 len(mesh_data.vertices), len(mesh_data.polygons))

    _apply_vertex_groups(br_mesh.vertex_groups, mesh_object)
    _add_armature_modifier(mesh_object, armature)

    mesh_data.update(calc_edges=True, calc_edges_loose=False)
    mesh_data.validate(verbose=False, clean_customdata=False)

    return mesh_object


def _apply_vertex_groups(vertex_groups, mesh_object):
    """Create Blender vertex groups and assign weights from a BRVertexGroup list.

    In: vertex_groups (list[BRVertexGroup]); mesh_object (bpy.types.Object).
    Out: None; vertex groups added in list order with REPLACE semantics.
    """
    for vg in vertex_groups:
        group = mesh_object.vertex_groups.new(name=vg.name)
        for vertex_index, weight in vg.assignments:
            group.add([vertex_index], weight, 'REPLACE')


def _add_armature_modifier(mesh_object, armature):
    """Attach a bone-envelope-disabled ARMATURE modifier named 'Skinmod'.

    In: mesh_object (bpy.types.Object); armature (bpy.types.Object).
    Out: None.
    """
    mod = mesh_object.modifiers.new('Skinmod', 'ARMATURE')
    mod.object = armature
    mod.use_bone_envelopes = False
    mod.use_vertex_groups = True
