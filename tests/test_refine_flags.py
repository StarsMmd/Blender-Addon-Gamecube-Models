"""Tests for _refine_bone_flags — the export-side JObj flag derivation.

Game-original sirnight, achamo, and bohmander all agree on the rule that
mesh-carrying bones use ENV_MODEL / HIDDEN alongside LIGHTING|OPA but never
also carry SKEL — even when those same bones are deformation targets for
other meshes. This test pins that rule down.
"""
from shared.IR.skeleton import IRBone
from shared.IR.geometry import IRMesh, IRBoneWeights
from shared.IR.enums import ScaleInheritance, SkinType
from shared.Constants.hsd import (
    JOBJ_SKELETON, JOBJ_SKELETON_ROOT, JOBJ_ENVELOPE_MODEL,
    JOBJ_LIGHTING, JOBJ_OPA, JOBJ_HIDDEN,
)
from exporter.phases.describe_blender.describe_blender import _refine_bone_flags
from shared.helpers.logger import StubLogger


def _identity_4x4():
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _make_bone(name, parent_index=None, mesh_indices=None, is_hidden=False):
    return IRBone(
        name=name,
        parent_index=parent_index,
        position=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1),
        inverse_bind_matrix=None,
        flags=0,
        is_hidden=is_hidden,
        inherit_scale=ScaleInheritance.ALIGNED,
        ik_shrink=False,
        world_matrix=_identity_4x4(),
        local_matrix=_identity_4x4(),
        normalized_world_matrix=_identity_4x4(),
        normalized_local_matrix=_identity_4x4(),
        scale_correction=_identity_4x4(),
        accumulated_scale=(1, 1, 1),
        mesh_indices=mesh_indices or [],
    )


def _make_mesh(name, parent_bone_index, bone_weights=None, is_hidden=False):
    return IRMesh(
        name=name,
        vertices=[(0, 0, 0)],
        faces=[],
        uv_layers=[],
        color_layers=[],
        normals=None,
        material=None,
        bone_weights=bone_weights,
        is_hidden=is_hidden,
        parent_bone_index=parent_bone_index,
        cull_back=False,
    )


class TestRefineBoneFlags:
    def test_mesh_bone_never_gets_skel_even_when_deformation_target(self):
        # root → mesh_bone; a second weighted mesh is also parented to mesh_bone
        # and references mesh_bone in its weights — so mesh_bone is BOTH a
        # mesh owner AND a deformation target. It must not carry SKEL.
        bones = [
            _make_bone("root"),
            _make_bone("mesh_bone", parent_index=0, mesh_indices=[0, 1]),
        ]
        weighted = IRBoneWeights(
            type=SkinType.WEIGHTED,
            assignments=[(0, [("mesh_bone", 1.0)])],
        )
        meshes = [
            _make_mesh("plain_mesh", parent_bone_index=1),
            _make_mesh("weighted_mesh", parent_bone_index=1, bone_weights=weighted),
        ]

        _refine_bone_flags(bones, meshes, StubLogger())

        assert bones[1].flags & JOBJ_SKELETON == 0, (
            "mesh-owning bone must not carry SKEL even when it's a weight target; "
            "flags=%#x" % bones[1].flags
        )
        assert bones[1].flags & JOBJ_LIGHTING != 0
        assert bones[1].flags & JOBJ_OPA != 0
        assert bones[1].flags & JOBJ_ENVELOPE_MODEL != 0

    def test_deformation_bone_without_mesh_keeps_skel(self):
        # mesh on bone[1] weighted to bone[2]: bone[2] is a deformation
        # target with no mesh attached — it should keep SKEL.
        bones = [
            _make_bone("root"),
            _make_bone("mesh_bone", parent_index=0, mesh_indices=[0]),
            _make_bone("deform_bone", parent_index=0),
        ]
        weighted = IRBoneWeights(
            type=SkinType.WEIGHTED,
            assignments=[(0, [("deform_bone", 1.0)])],
        )
        meshes = [_make_mesh("m", parent_bone_index=1, bone_weights=weighted)]

        _refine_bone_flags(bones, meshes, StubLogger())

        assert bones[2].flags & JOBJ_SKELETON != 0
        assert bones[2].flags & (JOBJ_LIGHTING | JOBJ_OPA | JOBJ_ENVELOPE_MODEL) == 0

    def test_hidden_mesh_bone_no_skel(self):
        bones = [
            _make_bone("root"),
            _make_bone("hidden_mesh_bone", parent_index=0, mesh_indices=[0]),
        ]
        meshes = [_make_mesh("m", parent_bone_index=1, is_hidden=True)]

        _refine_bone_flags(bones, meshes, StubLogger())

        assert bones[1].flags & JOBJ_HIDDEN != 0
        assert bones[1].flags & JOBJ_SKELETON == 0
        assert bones[1].flags & (JOBJ_LIGHTING | JOBJ_OPA) != 0
