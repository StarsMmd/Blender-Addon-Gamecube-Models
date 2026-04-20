"""Describe Blender mesh objects as IRMesh dataclasses.

Reads mesh objects parented to an armature, extracts geometry (vertices,
faces, UVs, vertex colors, normals) and bone weight data. Works with
any well-formed Blender mesh — no assumptions about naming conventions.
"""
import math
import bpy
from mathutils import Matrix

try:
    from .....shared.IR.geometry import IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights
    from .....shared.IR.enums import SkinType
    from .....shared.helpers.logger import StubLogger
    from .materials import describe_material
except (ImportError, SystemError):
    from shared.IR.geometry import IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights
    from shared.IR.enums import SkinType
    from shared.helpers.logger import StubLogger
    from exporter.phases.describe_blender.helpers.materials import describe_material

# Blender Z-up → GameCube Y-up (same constant as skeleton.py)
_COORD_ROTATION_INV = Matrix.Rotation(math.pi / 2, 4, [1.0, 0.0, 0.0]).inverted()


def describe_meshes(armature, bones, logger=StubLogger()):
    """Read mesh objects parented to an armature and produce IRMesh list.

    Args:
        armature: Blender armature object.
        bones: list[IRBone] from describe_skeleton (used for bone name lookup).
        logger: Logger instance.

    Returns:
        (meshes, blender_materials): two parallel lists of length N. The
        second list holds the bpy.types.Material (or None) each IRMesh was
        described from, which the material-animation exporter needs to
        recover the original `mesh_{idx}_{bone_name}` → material binding
        that the importer used when writing fcurves onto Blender materials.
    """
    bone_name_to_index = {bone.name: i for i, bone in enumerate(bones)}
    # Transform vertices and normals from Blender Z-up to GameCube Y-up.
    # The armature's matrix_world is identity (validated upstream by
    # describe_blender_scene), so no obj_transform is folded in here.
    vertex_transform = _COORD_ROTATION_INV
    normal_transform = _COORD_ROTATION_INV.to_3x3()
    meshes = []

    # Find all mesh objects parented to this armature, sorted by name.
    # Blender object names like "model_mesh_0", "model_mesh_1", etc. need
    # numeric sorting to preserve the original mesh order.
    mesh_objects = sorted(
        [obj for obj in bpy.data.objects
         if obj.type == 'MESH' and obj.parent == armature],
        key=_mesh_sort_key,
    )

    # Caches shared across all submeshes so that multiple mesh objects /
    # material slots referencing the same Blender material (or image) all
    # produce the same IRMaterial / IRImage Python instance. This is what
    # lets compose dedup collapse the whole MObject/TObject/Image subtree
    # down to one shared instance per material.
    material_cache = {}
    image_cache = {}

    blender_materials = []
    for mesh_obj in mesh_objects:
        ir_meshes, mats = _describe_mesh_object(
            mesh_obj, bone_name_to_index, bones,
            vertex_transform, normal_transform, logger,
            material_cache, image_cache)
        meshes.extend(ir_meshes)
        blender_materials.extend(mats)

    total_verts = sum(len(m.vertices) for m in meshes)
    total_faces = sum(len(m.faces) for m in meshes)
    weighted = sum(1 for m in meshes if m.bone_weights and m.bone_weights.type == SkinType.WEIGHTED)
    no_weights = sum(1 for m in meshes if not m.bone_weights)
    logger.info("  Described %d meshes from armature '%s': %d verts, %d faces (weighted=%d, no_weights=%d)",
                len(meshes), armature.name, total_verts, total_faces, weighted, no_weights)
    return meshes, blender_materials


def _describe_mesh_object(mesh_obj, bone_name_to_index, bones,
                          vertex_transform, normal_transform, logger,
                          material_cache=None, image_cache=None):
    """Extract geometry and weight data from a single Blender mesh object.

    If the mesh has multiple material slots with faces assigned, it is split
    into one IRMesh per material slot. This handles GLB/FBX models that use
    a single mesh with multiple materials.

    Args:
        mesh_obj: Blender mesh object (bpy.types.Object with mesh data).
        bone_name_to_index: dict mapping bone name → index in IRBone list.
        vertex_transform: 4x4 Matrix (Z-up → Y-up coord conversion only).
        normal_transform: 3x3 Matrix (Z-up → Y-up coord conversion only).
        logger: Logger instance.

    Returns:
        list[IRMesh] — one per material slot (or one for the whole mesh).
    """
    mesh_data = mesh_obj.data
    mesh_data.calc_loop_triangles()

    # Transform vertices from Blender space (Z-up) to IR space (Y-up, scaled).
    all_vertices = [tuple(vertex_transform @ v.co) for v in mesh_data.vertices]
    if not all_vertices:
        logger.debug("  Skipping mesh '%s': no vertices", mesh_obj.name)
        return [], []

    all_polys = list(mesh_data.polygons)
    if not all_polys:
        logger.debug("  Skipping mesh '%s': no faces", mesh_obj.name)
        return [], []

    # Read all per-loop data once
    all_uv_data = []
    for uv_layer in mesh_data.uv_layers:
        all_uv_data.append((uv_layer.name, [(d.uv[0], d.uv[1]) for d in uv_layer.data]))

    all_color_data = []
    for color_attr in mesh_data.color_attributes:
        all_color_data.append((color_attr.name, [tuple(cd.color) for cd in color_attr.data]))

    all_normals = _extract_normals(mesh_data, [list(p.vertices) for p in all_polys],
                                   normal_transform)

    # Shared across all sub-meshes
    bone_weights = _extract_bone_weights(mesh_obj, bone_name_to_index)
    parent_bone_index = _determine_parent_bone(mesh_obj, bone_weights, bone_name_to_index, bones)
    is_hidden = mesh_obj.hide_render

    # Determine material slot usage — group polygons by material_index
    num_materials = len(mesh_data.materials)
    if num_materials <= 1:
        # Single material (or none) — no splitting needed
        material_groups = [(0, list(range(len(all_polys))))]
    else:
        groups_by_mat = {}
        for pi, poly in enumerate(all_polys):
            mi = poly.material_index
            if mi not in groups_by_mat:
                groups_by_mat[mi] = []
            groups_by_mat[mi].append(pi)
        material_groups = sorted(groups_by_mat.items())

    results = []
    result_materials = []
    for mat_index, poly_indices in material_groups:
        if not poly_indices:
            continue

        ir_mesh, blender_mat = _build_submesh(
            mesh_obj.name, mat_index, num_materials,
            all_vertices, all_polys, poly_indices,
            all_uv_data, all_color_data, all_normals,
            bone_weights, parent_bone_index, is_hidden,
            mesh_data.materials, logger,
            material_cache, image_cache,
        )
        if ir_mesh is not None:
            results.append(ir_mesh)
            result_materials.append(blender_mat)

    return results, result_materials


def _build_submesh(mesh_name, mat_index, num_materials,
                   all_vertices, all_polys, poly_indices,
                   all_uv_data, all_color_data, all_normals,
                   bone_weights, parent_bone_index, is_hidden,
                   materials, logger,
                   material_cache=None, image_cache=None):
    """Build an IRMesh from a subset of polygons sharing one material.

    Remaps vertex indices and per-loop data so the sub-mesh is self-contained.
    """
    # Collect unique vertex indices used by these polygons and build remap
    used_verts = set()
    for pi in poly_indices:
        for vi in all_polys[pi].vertices:
            used_verts.add(vi)
    sorted_verts = sorted(used_verts)
    vert_remap = {old: new for new, old in enumerate(sorted_verts)}
    vertices = [all_vertices[vi] for vi in sorted_verts]

    # Remap faces and collect loop indices
    faces = []
    loop_indices = []  # flat list of original loop indices for this sub-mesh
    for pi in poly_indices:
        poly = all_polys[pi]
        faces.append([vert_remap[vi] for vi in poly.vertices])
        for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
            loop_indices.append(li)

    if not faces:
        return None, None

    # Remap per-loop UV data
    uv_layers = []
    for uv_name, uv_data in all_uv_data:
        uvs = [uv_data[li] for li in loop_indices]
        uv_layers.append(IRUVLayer(name=uv_name, uvs=uvs))

    # Remap per-loop color data
    color_layers = []
    for clr_name, clr_data in all_color_data:
        colors = [clr_data[li] for li in loop_indices]
        color_layers.append(IRColorLayer(name=clr_name, colors=colors))

    # Remap per-loop normals
    normals = None
    if all_normals:
        normals = [all_normals[li] for li in loop_indices]

    # Remap bone weights — filter to only vertices in this sub-mesh
    sub_weights = None
    if bone_weights:
        if bone_weights.type == SkinType.WEIGHTED and bone_weights.assignments:
            sub_assignments = []
            for old_vi, weight_list in bone_weights.assignments:
                if old_vi in vert_remap:
                    sub_assignments.append((vert_remap[old_vi], weight_list))
            if sub_assignments:
                sub_weights = IRBoneWeights(
                    type=SkinType.WEIGHTED,
                    assignments=sub_assignments,
                )
        else:
            sub_weights = bone_weights

    # Material
    ir_material = None
    blender_mat = None
    cull_back = False
    if materials and mat_index < len(materials) and materials[mat_index]:
        blender_mat = materials[mat_index]
        cull_back = blender_mat.use_backface_culling
        ir_material = describe_material(blender_mat, logger=logger,
                                        cache=material_cache,
                                        image_cache=image_cache)

    # Name: append material index suffix only when the mesh was split
    name = mesh_name if num_materials <= 1 else "%s_%03d" % (mesh_name, mat_index)

    ir_mesh = IRMesh(
        name=name,
        vertices=vertices,
        faces=faces,
        uv_layers=uv_layers,
        color_layers=color_layers,
        normals=normals,
        material=ir_material,
        bone_weights=sub_weights,
        is_hidden=is_hidden,
        parent_bone_index=parent_bone_index,
        cull_back=cull_back,
    )

    weight_type = sub_weights.type.value if sub_weights else 'none'
    weight_bone = sub_weights.bone_name if sub_weights and hasattr(sub_weights, 'bone_name') else None
    weight_count = len(sub_weights.assignments) if sub_weights and sub_weights.assignments else 0
    uv_names = [uv.name for uv in uv_layers]
    clr_names = [cl.name for cl in color_layers]
    logger.debug("  mesh '%s': %d verts, %d faces, parent_bone=%d, hidden=%s, cull_back=%s",
                 name, len(vertices), len(faces), parent_bone_index, is_hidden, cull_back)
    logger.debug("    uvs=%s, colors=%s, normals=%s",
                 uv_names, clr_names, len(normals) if normals else 'none')
    logger.debug("    weights: type=%s, bone=%s, assignments=%d",
                 weight_type, weight_bone, weight_count)
    return ir_mesh, blender_mat


def _mesh_sort_key(mesh_obj):
    """Sort key for mesh objects that handles numeric suffixes correctly.

    Sorts 'model_mesh_2' before 'model_mesh_10' (numeric, not alphabetic).
    """
    import re
    name = mesh_obj.name
    match = re.search(r'(\d+)$', name)
    if match:
        prefix = name[:match.start()]
        return (prefix, int(match.group(1)))
    return (name, 0)


def _extract_normals(mesh_data, faces, normal_transform=None):
    """Extract per-loop normals from mesh data.

    Uses corner_normals (Blender 4.1+). Falls back to loop.normal for
    older versions. Applies normal_transform (3x3 rotation matrix) to
    convert from Blender space to IR space.

    Returns:
        list[tuple[float, float, float]] per loop, or None if unavailable.
    """
    if not mesh_data.has_custom_normals:
        return None

    # Blender 4.1+ removed calc_normals_split(); normals are always
    # available via corner_normals.
    if hasattr(mesh_data, 'corner_normals'):
        raw = [cn.vector for cn in mesh_data.corner_normals]
    else:
        mesh_data.calc_normals_split()
        raw = [loop.normal for loop in mesh_data.loops]

    if normal_transform is not None:
        return [tuple(normal_transform @ n) for n in raw]
    return [(n.x, n.y, n.z) for n in raw]


def _extract_bone_weights(mesh_obj, bone_name_to_index):
    """Extract bone weight assignments from vertex groups.

    Classifies the mesh skinning as WEIGHTED, SINGLE_BONE, or returns None
    if no bone-related vertex groups exist.

    Args:
        mesh_obj: Blender mesh object.
        bone_name_to_index: dict mapping bone name → index.

    Returns:
        IRBoneWeights or None.
    """
    # Filter vertex groups to only those that match bone names
    bone_groups = {}
    for vg in mesh_obj.vertex_groups:
        if vg.name in bone_name_to_index:
            bone_groups[vg.index] = vg.name

    if not bone_groups:
        return None

    # Collect per-vertex weight assignments
    mesh_data = mesh_obj.data
    assignments = []
    bone_weight_totals = {}  # {bone_name: total_weight} for parent bone detection

    for vertex in mesh_data.vertices:
        weight_list = []
        for group_element in vertex.groups:
            group_idx = group_element.group
            if group_idx in bone_groups:
                bone_name = bone_groups[group_idx]
                weight = group_element.weight
                if weight > 0.0:
                    weight_list.append((bone_name, weight))
                    bone_weight_totals[bone_name] = bone_weight_totals.get(bone_name, 0.0) + weight

        if weight_list:
            assignments.append((vertex.index, weight_list))

    if not assignments:
        return None

    # Always emit WEIGHTED (envelope skinning) for vertex-grouped meshes.
    # The game's POBJ_SKIN format (SINGLE_BONE in the IR) is unused across
    # the 70+ surveyed Pokémon models — every weighted mesh is envelope,
    # even single-bone-weight=1.0 cases. Re-classifying to SINGLE_BONE
    # here would be ambiguous (Blender can't distinguish envelope-of-one
    # from rigid-skin-to-one) and would change the format on round-trip.
    return IRBoneWeights(
        type=SkinType.WEIGHTED,
        assignments=assignments,
    )


def _determine_parent_bone(mesh_obj, bone_weights, bone_name_to_index, bones):
    """Determine which bone index a mesh should be attached to.

    Preferred: the mesh object's `parent_bone` field — the importer sets
    this to preserve the original mesh→bone ownership through the
    round-trip. Works whether `parent_type` is OBJECT or BONE.
    Fallback for meshes authored outside our importer:
    - WEIGHTED: nearest common ancestor of all weighted bones.
    - Otherwise: 0 (root).

    Args:
        mesh_obj: Blender mesh object.
        bone_weights: IRBoneWeights or None.
        bone_name_to_index: dict mapping bone name → index.
        bones: list[IRBone] for parent chain traversal.

    Returns:
        int — bone index.
    """
    if mesh_obj.parent_bone:
        idx = bone_name_to_index.get(mesh_obj.parent_bone)
        if idx is not None:
            return idx

    if bone_weights is None:
        return 0

    if bone_weights.type == SkinType.WEIGHTED and bone_weights.assignments:
        # Collect all bones referenced in weight assignments
        referenced = set()
        for _, weight_list in bone_weights.assignments:
            for bone_name, _ in weight_list:
                idx = bone_name_to_index.get(bone_name)
                if idx is not None:
                    referenced.add(idx)

        if referenced:
            # Find nearest common ancestor
            def ancestors(idx):
                path = []
                while idx is not None:
                    path.append(idx)
                    idx = bones[idx].parent_index
                return path

            ancestor_lists = [ancestors(bi) for bi in referenced]
            common = set(ancestor_lists[0])
            for al in ancestor_lists[1:]:
                common &= set(al)

            if common:
                # Nearest = deepest in the tree (first match walking
                # up from any weighted bone)
                first_path = ancestor_lists[0]
                for idx in first_path:
                    if idx in common:
                        return idx

    return 0
