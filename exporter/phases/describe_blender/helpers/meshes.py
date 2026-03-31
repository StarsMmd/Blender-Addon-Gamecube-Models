"""Describe Blender mesh objects as IRMesh dataclasses.

Reads mesh objects parented to an armature, extracts geometry (vertices,
faces, UVs, vertex colors, normals) and bone weight data. Works with
any well-formed Blender mesh — no assumptions about naming conventions.
"""
import bpy
from mathutils import Matrix

try:
    from ......shared.IR.geometry import IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights
    from ......shared.IR.enums import SkinType
    from ......shared.helpers.logger import StubLogger
except (ImportError, SystemError):
    from shared.IR.geometry import IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights
    from shared.IR.enums import SkinType
    from shared.helpers.logger import StubLogger


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

    # Find all mesh objects parented to this armature
    mesh_objects = [
        obj for obj in bpy.data.objects
        if obj.type == 'MESH' and obj.parent == armature
    ]

    for mesh_obj in mesh_objects:
        ir_mesh = _describe_mesh_object(mesh_obj, bone_name_to_index, logger)
        if ir_mesh is not None:
            meshes.append(ir_mesh)

    logger.info("  Described %d meshes from armature '%s'", len(meshes), armature.name)
    return meshes


def _describe_mesh_object(mesh_obj, bone_name_to_index, logger):
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

    # Bone weights
    bone_weights = _extract_bone_weights(mesh_obj, bone_name_to_index)

    # Parent bone index — determined from bone weights
    parent_bone_index = _determine_parent_bone(bone_weights, bone_name_to_index)

    # Visibility
    is_hidden = mesh_obj.hide_render

    # Backface culling — read from the first material slot if present
    cull_back = False
    if mesh_obj.data.materials and mesh_obj.data.materials[0]:
        cull_back = mesh_obj.data.materials[0].use_backface_culling

    ir_mesh = IRMesh(
        name=mesh_obj.name,
        vertices=vertices,
        faces=faces,
        uv_layers=uv_layers,
        color_layers=color_layers,
        normals=normals,
        material=None,  # Material export not yet implemented
        bone_weights=bone_weights,
        is_hidden=is_hidden,
        parent_bone_index=parent_bone_index,
        cull_back=cull_back,
    )

    logger.debug("  mesh '%s': %d verts, %d faces, %d uv_layers, %d color_layers, parent_bone=%d",
                 mesh_obj.name, len(vertices), len(faces), len(uv_layers),
                 len(color_layers), parent_bone_index)
    return ir_mesh


def _extract_normals(mesh_data, faces):
    """Extract per-loop normals from mesh data.

    Returns:
        list[tuple[float, float, float]] per loop, or None if unavailable.
    """
    if not mesh_data.has_custom_normals:
        return None

    mesh_data.calc_normals_split()
    normals = []
    for loop in mesh_data.loops:
        n = loop.normal
        normals.append((n.x, n.y, n.z))
    return normals


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

    # Classify: if all vertices reference exactly one bone and it's the same bone → SINGLE_BONE
    referenced_bones = set()
    all_single = True
    for _, weight_list in assignments:
        if len(weight_list) != 1:
            all_single = False
            break
        referenced_bones.add(weight_list[0][0])

    if all_single and len(referenced_bones) == 1:
        bone_name = next(iter(referenced_bones))
        return IRBoneWeights(
            type=SkinType.SINGLE_BONE,
            bone_name=bone_name,
        )

    # Multiple bones → WEIGHTED
    return IRBoneWeights(
        type=SkinType.WEIGHTED,
        assignments=assignments,
    )


def _determine_parent_bone(bone_weights, bone_name_to_index):
    """Determine which bone index a mesh should be attached to.

    Uses the bone with the highest total vertex weight across all vertices.
    Falls back to 0 (root) if no weights exist.

    Args:
        bone_weights: IRBoneWeights or None.
        bone_name_to_index: dict mapping bone name → index.

    Returns:
        int — bone index.
    """
    if bone_weights is None:
        return 0

    if bone_weights.type == SkinType.SINGLE_BONE and bone_weights.bone_name:
        return bone_name_to_index.get(bone_weights.bone_name, 0)

    if bone_weights.type == SkinType.WEIGHTED and bone_weights.assignments:
        # Sum total weight per bone, pick the one with the highest total
        totals = {}
        for _, weight_list in bone_weights.assignments:
            for bone_name, weight in weight_list:
                totals[bone_name] = totals.get(bone_name, 0.0) + weight
        if totals:
            best_bone = max(totals, key=totals.get)
            return bone_name_to_index.get(best_bone, 0)

    return 0
