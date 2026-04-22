"""IR meshes → BR meshes conversion.

Pure — no bpy, no side effects. Flattens IR's three SkinType variants into
a uniform BRVertexGroup list, expands JOBJ_INSTANCE bones into per-mesh
BRMeshInstance entries, and pre-computes the mesh_key strings that link
material-animation tracks to their target meshes.
"""
try:
    from .....shared.BR.meshes import (
        BRMesh, BRMeshInstance, BRUVLayer, BRColorLayer, BRVertexGroup,
    )
    from .....shared.IR.enums import SkinType
except (ImportError, SystemError):
    from shared.BR.meshes import (
        BRMesh, BRMeshInstance, BRUVLayer, BRColorLayer, BRVertexGroup,
    )
    from shared.IR.enums import SkinType


def plan_meshes(ir_model):
    """Convert IRModel's meshes + instance bones into BR form.

    Returns:
        (list[BRMesh], list[BRMeshInstance]).
    """
    meshes_with_color_anim = _collect_color_animated_mesh_keys(ir_model)
    model_name = ir_model.name or "Model"
    mesh_digits = len(str(max(len(ir_model.meshes) - 1, 0)))

    br_meshes = []
    for i, ir_mesh in enumerate(ir_model.meshes):
        parent_bone_name = _lookup_parent_bone_name(ir_mesh.parent_bone_index, ir_model.bones)
        mesh_key = _make_mesh_key(i, mesh_digits, parent_bone_name)

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
            has_color_animation=mesh_key in meshes_with_color_anim,
            shape_keys=list(ir_mesh.shape_keys) if ir_mesh.shape_keys else [],
            material=ir_mesh.material,
            material_name='%s_mat_%d' % (model_name, i),
            material_cull_front=ir_mesh.cull_front,
            material_cull_back=ir_mesh.cull_back,
        ))

    br_instances = plan_mesh_instances(ir_model)
    return br_meshes, br_instances


def plan_vertex_groups(ir_mesh):
    """Flatten the three IR SkinType variants into a single BRVertexGroup list.

    - WEIGHTED: group per referenced bone, assignments collected from
      per-vertex weight lists.
    - SINGLE_BONE / RIGID: one group with every vertex weighted 1.0 to the
      named bone.
    """
    bw = ir_mesh.bone_weights
    if bw is None:
        return []

    if bw.type == SkinType.WEIGHTED and bw.assignments:
        groups = {}  # bone_name → list[(vertex_idx, weight)]
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
    """Expand JOBJ_INSTANCE bones into per-mesh BRMeshInstance entries.

    For each bone with ``instance_child_bone_index`` set, clone every mesh
    owned by the referenced source bone (via ``parent_bone_index``) and
    attach it at the current bone with the current bone's world matrix.
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


def _collect_color_animated_mesh_keys(ir_model):
    """Mesh keys whose diffuse RGB channels have any animation keyframes.

    Material animations target nodes by name, so the material builder needs
    to create a DiffuseColor node even for vertex-only unlit materials when
    color animation is present. Pre-computing this here keeps the build
    phase from having to re-scan animations.
    """
    keys = set()
    for anim_set in (ir_model.bone_animations or []):
        for mat_track in anim_set.material_tracks:
            if mat_track.diffuse_r or mat_track.diffuse_g or mat_track.diffuse_b:
                keys.add(mat_track.material_mesh_name)
    return keys


def _lookup_parent_bone_name(parent_bone_index, bones):
    if parent_bone_index is None or parent_bone_index >= len(bones):
        return None
    return bones[parent_bone_index].name


def _make_mesh_key(index, digit_width, parent_bone_name):
    return "mesh_%s_%s" % (str(index).zfill(digit_width), parent_bone_name or 'unknown')
