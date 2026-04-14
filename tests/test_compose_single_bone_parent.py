"""Regression: SINGLE_BONE inverse transform must use parent_bone_index.

The export pipeline transforms RIGID/SINGLE_BONE world-space vertices into
the parent JObj's local space, mirroring the importer's forward transform.
Previously the SINGLE_BONE branch overrode the bone with `bw.bone_name`,
which broke meshes whose original attachment bone differed from their
single-weight target — e.g. sirnight head extras parented to bone 107
but weighted entirely to bone 71. The exporter wrote bone-71-local
vertices into a DObj attached to JObj 107; on re-import, JObj 107's
identity world matrix left those vertices stranded near the model origin
instead of up by the head.
"""
import struct

from shared.IR.geometry import IRMesh, IRBoneWeights
from shared.IR.skeleton import IRBone
from shared.IR.enums import ScaleInheritance, SkinType
from exporter.phases.compose.helpers.bones import compose_bones
from exporter.phases.compose.helpers.meshes import compose_meshes


def _identity_4x4():
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _translation_4x4(x, y, z):
    return [[1, 0, 0, x], [0, 1, 0, y], [0, 0, 1, z], [0, 0, 0, 1]]


def _make_bone(name, parent_index=None, world_matrix=None):
    return IRBone(
        name=name,
        parent_index=parent_index,
        position=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1),
        inverse_bind_matrix=None,
        flags=0,
        is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED,
        ik_shrink=False,
        world_matrix=world_matrix or _identity_4x4(),
        local_matrix=_identity_4x4(),
        normalized_world_matrix=world_matrix or _identity_4x4(),
        normalized_local_matrix=_identity_4x4(),
        scale_correction=_identity_4x4(),
        accumulated_scale=(1, 1, 1),
    )


def _decode_pos_buffer(buf):
    """Decode a big-endian float3 vertex buffer into [(x,y,z), ...]."""
    n = len(buf) // 12
    return [struct.unpack('>3f', buf[i*12:(i+1)*12]) for i in range(n)]


def _first_pobj_positions(joint):
    pobj = joint.property.pobject
    # Vertex 'descriptors' live in vertex_list.vertices; attribute 9 = GX_VA_POS.
    pos_desc = next(d for d in pobj.vertex_list.vertices if d.attribute == 9)
    return _decode_pos_buffer(pos_desc.raw_vertex_data)


def test_single_bone_mesh_uses_parent_bone_world_for_inverse_transform():
    # Three bones: root at origin, attach_bone at origin, weight_bone way up.
    # The mesh attaches to attach_bone (parent_bone_index=1) but is
    # 100%-weighted to weight_bone (bone_name=weight_bone).
    bones = [
        _make_bone("root"),
        _make_bone("attach_bone", parent_index=0),                       # at origin
        _make_bone("weight_bone", parent_index=0,
                   world_matrix=_translation_4x4(0, 1.165, 0)),          # up high
    ]
    _, joints = compose_bones(bones)

    # Vertex sits at world y=1.165 — exactly where the weight_bone is.
    mesh = IRMesh(
        name="head_extra",
        vertices=[(0.0, 1.165, 0.0)],
        faces=[[0, 0, 0]],
        uv_layers=[], color_layers=[], normals=None, material=None,
        bone_weights=IRBoneWeights(
            type=SkinType.SINGLE_BONE,
            bone_name="weight_bone",
        ),
        is_hidden=False,
        parent_bone_index=1,                                              # attach_bone
        cull_back=False,
    )

    compose_meshes([mesh], joints, bones)

    encoded = _first_pobj_positions(joints[1])[0]
    # Exporter must inverse-transform by attach_bone (identity) → vertex
    # stays at (0, 1.165, 0). If it used weight_bone (the buggy path),
    # the encoded vertex would be (0, 0, 0) instead.
    assert abs(encoded[1] - 1.165) < 1e-4, (
        "Single-bone mesh inverse-transformed by the wrong bone: "
        "expected y=1.165 (parent=identity), got %.4f. The exporter is "
        "using bw.bone_name instead of parent_bone_index." % encoded[1]
    )
