"""Plan BRMesh list into IRMesh list.

Pure — no bpy. Applies the Blender Z-up → GameCube Y-up coordinate
rotation (kept as data on BR), packs BRVertexGroup back into the
per-vertex IRBoneWeights format, resolves parent-bone names to indices
(with nearest-common-ancestor fallback for unparented weighted meshes),
and attaches the parallel IRMaterials list provided by describe.
"""
import math

try:
    from .....shared.IR.geometry import (
        IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights,
    )
    from .....shared.IR.enums import SkinType
    from .....shared.helpers.logger import StubLogger
    from .materials import plan_materials
except (ImportError, SystemError):
    from shared.IR.geometry import (
        IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights,
    )
    from shared.IR.enums import SkinType
    from shared.helpers.logger import StubLogger
    from exporter.phases.plan.helpers.materials import plan_materials


def plan_meshes(br_meshes, br_materials, ir_bones, logger=StubLogger()):
    """Convert BR meshes (Blender frame) into IR meshes (GC frame).

    In: br_meshes (list[BRMesh]); br_materials (list[BRMaterial] indexed by
        BRMesh.material_index); ir_bones (list[IRBone] for parent_bone
        resolution); logger.
    Out: list[IRMesh].
    """
    bone_name_to_index = {b.name: i for i, b in enumerate(ir_bones)}
    ir_materials = plan_materials(br_materials, logger=logger)

    ir_meshes = []
    for br_mesh in br_meshes:
        bone_weights = _pack_bone_weights(br_mesh.vertex_groups)
        parent_bone_index = _resolve_parent_bone_index(
            br_mesh.parent_bone_name, br_mesh.vertex_groups,
            bone_name_to_index, ir_bones,
        )

        ir_material = None
        if br_mesh.material_index is not None and br_mesh.material_index < len(ir_materials):
            ir_material = ir_materials[br_mesh.material_index]

        ir_meshes.append(IRMesh(
            name=br_mesh.name,
            vertices=list(br_mesh.vertices),
            faces=[list(f) for f in br_mesh.faces],
            uv_layers=[
                IRUVLayer(name=uv.name, uvs=list(uv.uvs))
                for uv in br_mesh.uv_layers
            ],
            color_layers=[
                IRColorLayer(name=cl.name, colors=list(cl.colors))
                for cl in br_mesh.color_layers
            ],
            normals=list(br_mesh.normals) if br_mesh.normals else None,
            material=ir_material,
            bone_weights=bone_weights,
            is_hidden=br_mesh.is_hidden,
            parent_bone_index=parent_bone_index,
            cull_front=getattr(br_mesh, '_cull_front', False),
            cull_back=getattr(br_mesh, '_cull_back', False),
            id=br_mesh.id,
        ))

    logger.info("  Planned %d IRMesh(es) from BR", len(ir_meshes))
    return ir_meshes


def _pack_bone_weights(vertex_groups):
    """Invert BRVertexGroup (per-bone) into IRBoneWeights (per-vertex).

    Always emits SkinType.WEIGHTED — POBJ_SKIN/SINGLE_BONE is unused
    across the surveyed game models, and we can't safely re-classify a
    single-bone-weight=1.0 envelope mesh into rigid skin from a Blender
    scene alone.
    """
    if not vertex_groups:
        return None

    by_vertex = {}
    for vg in vertex_groups:
        for vertex_idx, weight in vg.assignments:
            by_vertex.setdefault(vertex_idx, []).append((vg.name, weight))

    if not by_vertex:
        return None

    assignments = sorted(by_vertex.items())
    return IRBoneWeights(
        type=SkinType.WEIGHTED,
        assignments=assignments,
    )


def determine_parent_bone(mesh_obj, ir_weights, bone_name_to_index, ir_bones):
    """Legacy-shaped helper used by tests: given a Blender-shaped mesh with
    ``parent_bone`` plus an ``IRBoneWeights`` (per-vertex bone lists), pick
    the bone index a mesh should attach to.

    Mirrors the responsibilities split between describe (parent_bone
    preference) and plan (NCA over weighted bones), so unit tests can
    exercise them in one call without spinning up the full pipeline.
    """
    parent_bone_name = (mesh_obj.parent_bone
                        if mesh_obj.parent_bone in bone_name_to_index else None)

    fake_groups = []
    if ir_weights and ir_weights.assignments:
        seen = set()
        for _, weight_list in ir_weights.assignments:
            for bone_name, _w in weight_list:
                if bone_name not in seen:
                    seen.add(bone_name)
                    fake_groups.append(_FakeVG(name=bone_name, assignments=[]))

    return _resolve_parent_bone_index(
        parent_bone_name, fake_groups, bone_name_to_index, ir_bones,
    )


class _FakeVG:
    """Minimal duck-typed BRVertexGroup for ``determine_parent_bone``'s
    legacy adapter — we only use the ``name`` field."""
    __slots__ = ('name', 'assignments')

    def __init__(self, name, assignments):
        self.name = name
        self.assignments = assignments


def _resolve_parent_bone_index(parent_bone_name, vertex_groups,
                               bone_name_to_index, ir_bones):
    """Pick a parent bone index for a mesh that hangs off an armature.

    Preferred: ``parent_bone_name`` set by describe (preserves
    importer-side ownership). Otherwise, the nearest common ancestor of
    every bone the mesh has weights on. Fallback: 0 (root).
    """
    if parent_bone_name:
        idx = bone_name_to_index.get(parent_bone_name)
        if idx is not None:
            return idx

    if not vertex_groups:
        return 0

    referenced = set()
    for vg in vertex_groups:
        idx = bone_name_to_index.get(vg.name)
        if idx is not None:
            referenced.add(idx)
    if not referenced:
        return 0

    def ancestors(idx):
        chain = []
        while idx is not None:
            chain.append(idx)
            idx = ir_bones[idx].parent_index
        return chain

    chains = [ancestors(i) for i in referenced]
    common = set(chains[0])
    for c in chains[1:]:
        common &= set(c)
    if not common:
        return 0

    # Nearest = deepest = first match walking up from any weighted bone
    for idx in chains[0]:
        if idx in common:
            return idx
    return 0
