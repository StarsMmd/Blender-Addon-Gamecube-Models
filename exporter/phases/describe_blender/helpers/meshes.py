"""Describe Blender mesh objects as IRMesh dataclasses.

Reads mesh objects parented to an armature, extracts geometry (vertices,
faces, UVs, vertex colors, normals) and bone weight data. Works with
any well-formed Blender mesh — no assumptions about naming conventions.
"""
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


def describe_meshes(armature, bones, logger=StubLogger()):
    """Read mesh objects parented to an armature and produce IRMesh list.

    Args:
        armature: Blender armature object.
        bones: list[IRBone] from describe_skeleton (used for bone name lookup).
        logger: Logger instance.

    Returns:
        list[IRMesh] — one entry per mesh object found.
    """
    bone_name_to_index = {bone.name: i for i, bone in enumerate(bones)}
    meshes = []

    # Find all mesh objects parented to this armature, sorted by name.
    # Blender object names like "model_mesh_0", "model_mesh_1", etc. need
    # numeric sorting to preserve the original mesh order.
    mesh_objects = sorted(
        [obj for obj in bpy.data.objects
         if obj.type == 'MESH' and obj.parent == armature],
        key=_mesh_sort_key,
    )

    for mesh_obj in mesh_objects:
        ir_mesh = _describe_mesh_object(mesh_obj, bone_name_to_index, bones, logger)
        if ir_mesh is not None:
            meshes.append(ir_mesh)

    total_verts = sum(len(m.vertices) for m in meshes)
    total_faces = sum(len(m.faces) for m in meshes)
    weighted = sum(1 for m in meshes if m.bone_weights and m.bone_weights.type == SkinType.WEIGHTED)
    single = sum(1 for m in meshes if m.bone_weights and m.bone_weights.type == SkinType.SINGLE_BONE)
    no_weights = sum(1 for m in meshes if not m.bone_weights)
    logger.info("  Described %d meshes from armature '%s': %d verts, %d faces (weighted=%d, single_bone=%d, no_weights=%d)",
                len(meshes), armature.name, total_verts, total_faces, weighted, single, no_weights)
    return meshes


def _describe_mesh_object(mesh_obj, bone_name_to_index, bones, logger):
    """Extract geometry and weight data from a single Blender mesh object.

    Args:
        mesh_obj: Blender mesh object (bpy.types.Object with mesh data).
        bone_name_to_index: dict mapping bone name → index in IRBone list.
        logger: Logger instance.

    Returns:
        IRMesh, or None if the mesh has no geometry.
    """
    mesh_data = mesh_obj.data

    # Ensure geometry is up to date
    mesh_data.calc_loop_triangles()

    # Vertices
    vertices = [tuple(v.co) for v in mesh_data.vertices]
    if not vertices:
        logger.debug("  Skipping mesh '%s': no vertices", mesh_obj.name)
        return None

    # Faces — from polygons (not triangulated, preserving original topology)
    faces = [list(poly.vertices) for poly in mesh_data.polygons]
    if not faces:
        logger.debug("  Skipping mesh '%s': no faces", mesh_obj.name)
        return None

    # UV layers — stored per-loop in Blender
    uv_layers = []
    for uv_layer in mesh_data.uv_layers:
        uvs = [(loop_uv.uv[0], loop_uv.uv[1]) for loop_uv in uv_layer.data]
        uv_layers.append(IRUVLayer(name=uv_layer.name, uvs=uvs))

    # Color layers — read as-is (FLOAT_COLOR stores sRGB values, matching IR convention)
    color_layers = []
    for color_attr in mesh_data.color_attributes:
        colors = [tuple(cd.color) for cd in color_attr.data]
        color_layers.append(IRColorLayer(name=color_attr.name, colors=colors))

    # Normals — per-loop custom split normals if available
    normals = _extract_normals(mesh_data, faces)

    # Bone weights and parent bone index
    bone_weights = _extract_bone_weights(mesh_obj, bone_name_to_index)
    parent_bone_index = _determine_parent_bone(bone_weights, bone_name_to_index, bones)

    # Visibility
    is_hidden = mesh_obj.hide_render

    # Material — extract from first material slot
    ir_material = None
    cull_back = False
    if mesh_obj.data.materials and mesh_obj.data.materials[0]:
        blender_mat = mesh_obj.data.materials[0]
        cull_back = blender_mat.use_backface_culling
        ir_material = describe_material(blender_mat, logger=logger)

    ir_mesh = IRMesh(
        name=mesh_obj.name,
        vertices=vertices,
        faces=faces,
        uv_layers=uv_layers,
        color_layers=color_layers,
        normals=normals,
        material=ir_material,
        bone_weights=bone_weights,
        is_hidden=is_hidden,
        parent_bone_index=parent_bone_index,
        cull_back=cull_back,
    )

    # Log mesh details
    weight_type = bone_weights.type.value if bone_weights else 'none'
    weight_bone = bone_weights.bone_name if bone_weights and hasattr(bone_weights, 'bone_name') else None
    weight_count = len(bone_weights.assignments) if bone_weights and bone_weights.assignments else 0
    uv_names = [uv.name for uv in uv_layers]
    clr_names = [cl.name for cl in color_layers]
    logger.debug("  mesh '%s': %d verts, %d faces, parent_bone=%d, hidden=%s, cull_back=%s",
                 mesh_obj.name, len(vertices), len(faces), parent_bone_index, is_hidden, cull_back)
    logger.debug("    uvs=%s, colors=%s, normals=%s",
                 uv_names, clr_names, len(normals) if normals else 'none')
    logger.debug("    weights: type=%s, bone=%s, assignments=%d",
                 weight_type, weight_bone, weight_count)
    return ir_mesh


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


def _extract_normals(mesh_data, faces):
    """Extract per-loop normals from mesh data.

    Uses corner_normals (Blender 4.1+). Falls back to loop.normal for
    older versions.

    Returns:
        list[tuple[float, float, float]] per loop, or None if unavailable.
    """
    if not mesh_data.has_custom_normals:
        return None

    # Blender 4.1+ removed calc_normals_split(); normals are always
    # available via corner_normals.
    if hasattr(mesh_data, 'corner_normals'):
        return [(cn.vector.x, cn.vector.y, cn.vector.z)
                for cn in mesh_data.corner_normals]

    mesh_data.calc_normals_split()
    return [(loop.normal.x, loop.normal.y, loop.normal.z)
            for loop in mesh_data.loops]


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

    # Classify skinning type
    referenced_bones = set()
    all_single = True
    for _, weight_list in assignments:
        if len(weight_list) != 1:
            all_single = False
        for bone_name, _ in weight_list:
            referenced_bones.add(bone_name)

    # All vertices reference exactly one bone → SINGLE_BONE
    if all_single and len(referenced_bones) == 1:
        bone_name = next(iter(referenced_bones))
        return IRBoneWeights(
            type=SkinType.SINGLE_BONE,
            bone_name=bone_name,
        )

    # Multiple bones referenced — use WEIGHTED to preserve per-vertex
    # bone assignments. The compose phase encodes these as EnvelopeList
    # entries (HSD envelope skinning).
    return IRBoneWeights(
        type=SkinType.WEIGHTED,
        assignments=assignments,
    )


def _determine_parent_bone(bone_weights, bone_name_to_index, bones):
    """Determine which bone index a mesh should be attached to.

    For SINGLE_BONE: uses the named bone directly.
    For WEIGHTED: finds the nearest common ancestor of all bones
    referenced in the weight assignments.
    Falls back to 0 (root) if no weights exist.

    Args:
        bone_weights: IRBoneWeights or None.
        bone_name_to_index: dict mapping bone name → index.
        bones: list[IRBone] for parent chain traversal.

    Returns:
        int — bone index.
    """
    if bone_weights is None:
        return 0

    if bone_weights.type == SkinType.SINGLE_BONE and bone_weights.bone_name:
        return bone_name_to_index.get(bone_weights.bone_name, 0)

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
