"""Merge compatible IRMeshes into single batches.

Each Blender mesh object parented to an armature produces one IRMesh per
material slot in `describe_meshes`. When several Blender meshes on the
same armature share a material and parent bone, they flow through compose
as separate PObjects chained under one DObject. Merging them here packs
the whole run into a single PObject (compose's envelope-palette split
still runs afterwards, so no correctness risk) and keeps the authored
Blender scene untouched.

In: list[IRMesh]
Out: list[IRMesh], one per distinct (parent_bone, material, skin-shape,
     cull / hidden flags, local matrix, uv/color layer layout, shape keys)
     group.
"""
try:
    from .....shared.IR.geometry import IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights
    from .....shared.IR.enums import SkinType
    from .....shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.geometry import IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights
    from shared.IR.enums import SkinType
    from shared.helpers.logger import StubLogger


def _layer_names(layers):
    return tuple(layer.name for layer in layers)


def _weights_shape(bw):
    if bw is None:
        return ('NONE',)
    if bw.type == SkinType.WEIGHTED:
        return ('WEIGHTED',)
    return (bw.type.name if hasattr(bw.type, 'name') else str(bw.type),
            bw.bone_name)


def _merge_key(m):
    return (
        m.parent_bone_index,
        id(m.material),
        m.is_hidden,
        m.cull_front,
        m.cull_back,
        tuple(tuple(row) for row in m.local_matrix) if m.local_matrix else None,
        _layer_names(m.uv_layers),
        _layer_names(m.color_layers),
        m.normals is None,
        m.shape_keys is not None and len(m.shape_keys) > 0,
        _weights_shape(m.bone_weights),
    )


def _concat_bone_weights(base, addition, offset):
    if base is None and addition is None:
        return None

    btype = base.type if base is not None else addition.type
    merged_assignments = None
    if base is not None and base.assignments is not None:
        merged_assignments = list(base.assignments)
    if addition is not None and addition.assignments is not None:
        if merged_assignments is None:
            merged_assignments = []
        for vert_idx, bone_list in addition.assignments:
            merged_assignments.append((vert_idx + offset, list(bone_list)))

    merged_def_v = None
    if base is not None and base.deformed_vertices is not None:
        merged_def_v = list(base.deformed_vertices)
    if addition is not None and addition.deformed_vertices is not None:
        if merged_def_v is None:
            merged_def_v = []
        merged_def_v.extend(addition.deformed_vertices)

    merged_def_n = None
    if base is not None and base.deformed_normals is not None:
        merged_def_n = list(base.deformed_normals)
    if addition is not None and addition.deformed_normals is not None:
        if merged_def_n is None:
            merged_def_n = []
        merged_def_n.extend(addition.deformed_normals)

    return IRBoneWeights(
        type=btype,
        assignments=merged_assignments,
        bone_name=base.bone_name if base is not None else addition.bone_name,
        deformed_vertices=merged_def_v,
        deformed_normals=merged_def_n,
    )


def _merge_pair(acc, m):
    offset = len(acc.vertices)

    acc.vertices.extend(m.vertices)
    for face in m.faces:
        acc.faces.append([idx + offset for idx in face])

    for acc_layer, m_layer in zip(acc.uv_layers, m.uv_layers):
        acc_layer.uvs.extend(m_layer.uvs)
    for acc_layer, m_layer in zip(acc.color_layers, m.color_layers):
        acc_layer.colors.extend(m_layer.colors)

    if acc.normals is not None and m.normals is not None:
        acc.normals.extend(m.normals)

    acc.bone_weights = _concat_bone_weights(acc.bone_weights, m.bone_weights, offset)


def _clone_seed(m):
    return IRMesh(
        name=m.name,
        vertices=list(m.vertices),
        faces=[list(f) for f in m.faces],
        uv_layers=[IRUVLayer(name=u.name, uvs=list(u.uvs)) for u in m.uv_layers],
        color_layers=[IRColorLayer(name=c.name, colors=list(c.colors))
                      for c in m.color_layers],
        normals=list(m.normals) if m.normals is not None else None,
        material=m.material,
        bone_weights=_concat_bone_weights(None, m.bone_weights, 0),
        shape_keys=m.shape_keys,
        is_hidden=m.is_hidden,
        parent_bone_index=m.parent_bone_index,
        local_matrix=m.local_matrix,
        cull_front=m.cull_front,
        cull_back=m.cull_back,
    )


def merge_meshes(meshes, parallel=None, logger=StubLogger()):
    """Merge IRMeshes that share a compatible (bone, material, layout) key.

    Stable order — groups are emitted in the order their first IRMesh
    appeared in the input, and subsequent meshes fold into that seed.
    Shape-key-bearing meshes are never merged (morph targets would need
    their own vertex-position concatenation to stay valid).

    In:
        meshes: list[IRMesh]
        parallel: optional list the same length as `meshes` whose entries
            are kept aligned with the output. The entry from each group's
            seed mesh is retained; folded-in entries are dropped.
    Out:
        If `parallel` is None → list[IRMesh].
        Else → (list[IRMesh], list[parallel's element type]).
    """
    if len(meshes) < 2:
        return list(meshes) if parallel is None else (list(meshes), list(parallel))

    if parallel is not None and len(parallel) != len(meshes):
        raise ValueError("parallel list length must match meshes length")

    groups = {}
    group_parallel = {}
    order = []
    passthrough_meshes = []
    passthrough_parallel = []

    for i, m in enumerate(meshes):
        par_entry = parallel[i] if parallel is not None else None
        if m.shape_keys:
            passthrough_meshes.append(m)
            if parallel is not None:
                passthrough_parallel.append(par_entry)
            continue
        key = _merge_key(m)
        if key not in groups:
            groups[key] = _clone_seed(m)
            group_parallel[key] = par_entry
            order.append(key)
        else:
            _merge_pair(groups[key], m)

    merged = [groups[k] for k in order]
    before = len(meshes)
    after = len(merged) + len(passthrough_meshes)
    if after < before:
        logger.info("  Mesh merge: %d IRMesh(es) → %d", before, after)

    if parallel is None:
        return merged + passthrough_meshes

    merged_parallel = [group_parallel[k] for k in order] + passthrough_parallel
    return merged + passthrough_meshes, merged_parallel
