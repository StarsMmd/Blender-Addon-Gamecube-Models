"""IR meshes → BR meshes conversion.

Pure — no bpy, no side effects. Flattens IR's three SkinType variants into
a uniform BRVertexGroup list, expands JOBJ_INSTANCE bones into per-mesh
BRMeshInstance entries, and — together with plan_materials_for_meshes —
dedups IRMaterial references into a shared BRMaterial list so identical
(material, cull_front, cull_back) triples get one bpy material.
"""
try:
    from .....shared.BR.meshes import (
        BRMesh, BRMeshInstance, BRUVLayer, BRColorLayer, BRVertexGroup,
    )
    from .....shared.IR.enums import SkinType
    from .materials import plan_material
except (ImportError, SystemError):
    from shared.BR.meshes import (
        BRMesh, BRMeshInstance, BRUVLayer, BRColorLayer, BRVertexGroup,
    )
    from shared.IR.enums import SkinType
    from importer.phases.plan.helpers.materials import plan_material


def plan_meshes(ir_model):
    """Convert IRModel's meshes + instance bones into BR form.

    Returns:
        (br_meshes, br_instances, br_materials).
        br_meshes: list[BRMesh] — each ``material_index`` points into br_materials.
        br_instances: list[BRMeshInstance].
        br_materials: list[BRMaterial] — deduped shader graphs.
    """
    mesh_keys_with_color_anim = _collect_color_animated_mesh_keys(ir_model)
    model_name = ir_model.name or "Model"
    mesh_digits = len(str(max(len(ir_model.meshes) - 1, 0)))

    # First pass: build mesh keys + figure out which materials need a
    # DiffuseColor node (true if any mesh using that material has color anim).
    mesh_rows = []
    color_anim_by_material_key = {}
    for i, ir_mesh in enumerate(ir_model.meshes):
        parent_bone_name = _lookup_parent_bone_name(ir_mesh.parent_bone_index, ir_model.bones)
        mesh_key = _make_mesh_key(i, mesh_digits, parent_bone_name)
        has_color_anim = mesh_key in mesh_keys_with_color_anim
        material_key = _material_dedup_key(ir_mesh)
        if material_key is not None and has_color_anim:
            color_anim_by_material_key[material_key] = True
        mesh_rows.append((i, ir_mesh, parent_bone_name, mesh_key, material_key))

    # Second pass: dedup materials. For each unique material_key, call
    # plan_material once. Build index map so meshes can reference their
    # material by index.
    br_materials = []
    material_index_by_key = {}
    for i, ir_mesh, _parent_name, _mesh_key, material_key in mesh_rows:
        if material_key is None:
            continue
        if material_key in material_index_by_key:
            continue
        has_color_anim = color_anim_by_material_key.get(material_key, False)
        br_materials.append(plan_material(
            ir_mesh.material,
            name='%s_mat_%d' % (model_name, i),
            has_color_animation=has_color_anim,
            cull_front=ir_mesh.cull_front,
            cull_back=ir_mesh.cull_back,
            dedup_key=material_key,
        ))
        material_index_by_key[material_key] = len(br_materials) - 1

    # Third pass: emit BRMesh per IRMesh, pointing at the deduped material.
    br_meshes = []
    for i, ir_mesh, parent_bone_name, mesh_key, material_key in mesh_rows:
        material_index = material_index_by_key.get(material_key) if material_key else None
        br_meshes.append(BRMesh(
            name='%s_mesh_%s' % (model_name, ir_mesh.name),
            mesh_key=mesh_key,
            vertices=list(ir_mesh.vertices),
            faces=[list(face) for face in ir_mesh.faces],
            uv_layers=[
                BRUVLayer(name=uv.name, uvs=list(uv.uvs))
                for uv in ir_mesh.uv_layers
            ],
            color_layers=[
                BRColorLayer(name=cl.name, colors=list(cl.colors))
                for cl in ir_mesh.color_layers
            ],
            normals=list(ir_mesh.normals) if ir_mesh.normals else None,
            vertex_groups=plan_vertex_groups(ir_mesh),
            parent_bone_name=parent_bone_name,
            is_hidden=ir_mesh.is_hidden,
            shape_keys=list(ir_mesh.shape_keys) if ir_mesh.shape_keys else [],
            material_index=material_index,
        ))

    br_instances = plan_mesh_instances(ir_model)
    return br_meshes, br_instances, br_materials


def plan_vertex_groups(ir_mesh):
    """Flatten the three IR SkinType variants into a single BRVertexGroup list.

    In: ir_mesh (IRMesh).
    Out: list[BRVertexGroup] — empty if bone_weights is None; WEIGHTED produces
         one group per referenced bone; SINGLE_BONE/RIGID produce one group with
         every vertex at weight 1.0.
    """
    bw = ir_mesh.bone_weights
    if bw is None:
        return []

    if bw.type == SkinType.WEIGHTED and bw.assignments:
        groups = {}
        for vertex_idx, weight_list in bw.assignments:
            for bone_name, weight in weight_list:
                groups.setdefault(bone_name, []).append((vertex_idx, weight))
        return [BRVertexGroup(name=name, assignments=pairs) for name, pairs in groups.items()]

    if bw.type in (SkinType.SINGLE_BONE, SkinType.RIGID) and bw.bone_name:
        vertex_count = len(ir_mesh.vertices)
        return [BRVertexGroup(
            name=bw.bone_name,
            assignments=[(i, 1.0) for i in range(vertex_count)],
        )]

    return []


def plan_mesh_instances(ir_model):
    """Expand JOBJ_INSTANCE bones into BRMeshInstance entries.

    In: ir_model (IRModel).
    Out: list[BRMeshInstance] — one entry per (instanced source mesh, target bone)
         pair, carrying the target bone's world matrix as matrix_local.
    """
    meshes_by_source_bone = {}
    for mesh_index, ir_mesh in enumerate(ir_model.meshes):
        meshes_by_source_bone.setdefault(ir_mesh.parent_bone_index, []).append(mesh_index)

    instances = []
    for bone in ir_model.bones:
        if bone.instance_child_bone_index is None:
            continue
        for mesh_index in meshes_by_source_bone.get(bone.instance_child_bone_index, []):
            instances.append(BRMeshInstance(
                source_mesh_index=mesh_index,
                target_parent_bone_name=bone.name,
                matrix_local=bone.world_matrix,
            ))
    return instances


def _material_dedup_key(ir_mesh):
    """Dedup key for a mesh's material: (id(ir_material), cull_front, cull_back).

    In: ir_mesh (IRMesh).
    Out: tuple(int, bool, bool) or None when the mesh has no material.
    """
    if ir_mesh.material is None:
        return None
    return (id(ir_mesh.material), ir_mesh.cull_front, ir_mesh.cull_back)


def _collect_color_animated_mesh_keys(ir_model):
    """Mesh keys whose materials need a DiffuseColor fcurve target.

    In: ir_model (IRModel).
    Out: set[str] of mesh_key strings (matches BRMesh.mesh_key format) for
         every mesh whose bone_animations include any diffuse RGB keyframe.
    """
    keys = set()
    for anim_set in (ir_model.bone_animations or []):
        for mat_track in anim_set.material_tracks:
            if mat_track.diffuse_r or mat_track.diffuse_g or mat_track.diffuse_b:
                keys.add(mat_track.material_mesh_name)
    return keys


def _lookup_parent_bone_name(parent_bone_index, bones):
    """Safe name lookup — returns None for out-of-range indices.

    In: parent_bone_index (int|None); bones (list[IRBone]).
    Out: str|None.
    """
    if parent_bone_index is None or parent_bone_index >= len(bones):
        return None
    return bones[parent_bone_index].name


def _make_mesh_key(index, digit_width, parent_bone_name):
    """Stable mesh key used to bind material-animation tracks to their mesh.

    In: index (int); digit_width (int, padding); parent_bone_name (str|None).
    Out: str — 'mesh_{NN}_{bone_name or unknown}'.
    """
    return "mesh_%s_%s" % (str(index).zfill(digit_width), parent_bone_name or 'unknown')
