"""Unit tests for the Plan phase's IR meshes → BR meshes helper."""
from shared.IR.skeleton import IRBone, IRModel
from shared.IR.enums import ScaleInheritance, SkinType, Interpolation
from shared.IR.geometry import IRMesh, IRUVLayer, IRColorLayer, IRBoneWeights
from shared.IR.animation import (
    IRBoneAnimationSet, IRBoneTrack, IRMaterialTrack, IRKeyframe,
)
from shared.BR.meshes import BRMesh, BRMeshInstance, BRVertexGroup
from shared.helpers.math_shim import Matrix, matrix_to_list
from importer.phases.plan.helpers.meshes import (
    plan_meshes,
    plan_vertex_groups,
    plan_mesh_instances,
)


def _make_bone(name, parent_index=None, instance_child_bone_index=None,
               world_matrix=None):
    identity = matrix_to_list(Matrix.Identity(4))
    return IRBone(
        name=name,
        parent_index=parent_index,
        position=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        inverse_bind_matrix=None,
        flags=0,
        is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED,
        ik_shrink=False,
        world_matrix=world_matrix or identity,
        local_matrix=identity,
        normalized_world_matrix=identity,
        normalized_local_matrix=identity,
        scale_correction=identity,
        accumulated_scale=(1.0, 1.0, 1.0),
        instance_child_bone_index=instance_child_bone_index,
    )


def _make_mesh(name="m", parent_bone_index=0, vertices=None, faces=None,
               bone_weights=None, material=None, uv_layers=None,
               color_layers=None, normals=None, cull_front=False,
               cull_back=False, is_hidden=False):
    return IRMesh(
        name=name,
        vertices=vertices if vertices is not None else [(0, 0, 0), (1, 0, 0), (0, 1, 0)],
        faces=faces if faces is not None else [[0, 1, 2]],
        uv_layers=uv_layers or [],
        color_layers=color_layers or [],
        normals=normals,
        material=material,
        bone_weights=bone_weights,
        parent_bone_index=parent_bone_index,
        cull_front=cull_front,
        cull_back=cull_back,
        is_hidden=is_hidden,
    )


class TestPlanVertexGroups:

    def test_no_weights_yields_empty(self):
        mesh = _make_mesh()
        assert plan_vertex_groups(mesh) == []

    def test_single_bone_skin_yields_one_group_all_vertices(self):
        mesh = _make_mesh(
            vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)],
            bone_weights=IRBoneWeights(type=SkinType.SINGLE_BONE, bone_name='Bone_05'),
        )
        groups = plan_vertex_groups(mesh)
        assert len(groups) == 1
        assert groups[0].name == 'Bone_05'
        assert groups[0].assignments == [(0, 1.0), (1, 1.0), (2, 1.0), (3, 1.0)]

    def test_rigid_skin_behaves_like_single_bone(self):
        mesh = _make_mesh(
            vertices=[(0, 0, 0), (1, 0, 0)],
            bone_weights=IRBoneWeights(type=SkinType.RIGID, bone_name='Bone_02'),
        )
        groups = plan_vertex_groups(mesh)
        assert len(groups) == 1
        assert groups[0].name == 'Bone_02'
        assert groups[0].assignments == [(0, 1.0), (1, 1.0)]

    def test_weighted_skin_groups_by_bone_name(self):
        mesh = _make_mesh(
            bone_weights=IRBoneWeights(
                type=SkinType.WEIGHTED,
                assignments=[
                    (0, [('Bone_A', 0.7), ('Bone_B', 0.3)]),
                    (1, [('Bone_A', 1.0)]),
                    (2, [('Bone_B', 0.5), ('Bone_C', 0.5)]),
                ],
            ),
        )
        groups = {g.name: g.assignments for g in plan_vertex_groups(mesh)}
        assert set(groups) == {'Bone_A', 'Bone_B', 'Bone_C'}
        assert groups['Bone_A'] == [(0, 0.7), (1, 1.0)]
        assert groups['Bone_B'] == [(0, 0.3), (2, 0.5)]
        assert groups['Bone_C'] == [(2, 0.5)]


class TestPlanMeshInstances:

    def test_no_instance_bones_yields_empty(self):
        ir = IRModel(
            name="rig",
            bones=[_make_bone("A"), _make_bone("B", parent_index=0)],
            meshes=[_make_mesh("m0", parent_bone_index=1)],
        )
        assert plan_mesh_instances(ir) == []

    def test_instance_bone_copies_every_mesh_of_source(self):
        inst_world = matrix_to_list(Matrix.Identity(4))
        inst_world[0][3] = 5.0  # translate instance by X=5
        ir = IRModel(
            name="rig",
            bones=[
                _make_bone("Source"),
                _make_bone("Target", instance_child_bone_index=0, world_matrix=inst_world),
            ],
            meshes=[
                _make_mesh("m0", parent_bone_index=0),
                _make_mesh("m1", parent_bone_index=0),
            ],
        )
        instances = plan_mesh_instances(ir)
        assert len(instances) == 2
        assert all(isinstance(i, BRMeshInstance) for i in instances)
        assert {i.source_mesh_index for i in instances} == {0, 1}
        for i in instances:
            assert i.target_parent_bone_name == 'Target'
            assert i.matrix_local[0][3] == 5.0


class TestPlanMeshes:

    def test_simple_mesh_translated(self):
        ir = IRModel(
            name="rig",
            bones=[_make_bone("Root")],
            meshes=[_make_mesh("body", parent_bone_index=0)],
        )
        br_meshes, br_instances, br_materials = plan_meshes(ir)
        assert len(br_meshes) == 1
        assert isinstance(br_meshes[0], BRMesh)
        m = br_meshes[0]
        assert m.name == 'rig_mesh_body'
        assert m.mesh_key == 'mesh_0_Root'
        assert m.parent_bone_name == 'Root'
        assert m.is_hidden is False
        assert m.material_index is None  # no IR material was supplied
        assert br_instances == []
        assert br_materials == []

    def test_mesh_key_uses_zero_padded_index(self):
        """Mesh keys must sort stably — width driven by total count."""
        ir = IRModel(
            name="rig",
            bones=[_make_bone("Root")],
            meshes=[_make_mesh(f"m{i}", parent_bone_index=0) for i in range(12)],
        )
        br_meshes, _, _ = plan_meshes(ir)
        # 12 meshes → indices need 2 digits
        assert br_meshes[0].mesh_key == 'mesh_00_Root'
        assert br_meshes[9].mesh_key == 'mesh_09_Root'
        assert br_meshes[10].mesh_key == 'mesh_10_Root'

    def test_out_of_range_parent_bone_index_becomes_none(self):
        ir = IRModel(
            name="rig",
            bones=[_make_bone("Root")],
            meshes=[_make_mesh("orphan", parent_bone_index=99)],
        )
        br_meshes, _, _ = plan_meshes(ir)
        assert br_meshes[0].parent_bone_name is None
        assert br_meshes[0].mesh_key == 'mesh_0_unknown'

    def test_meshes_without_material_get_none_index(self):
        """Meshes with no IR material → ``material_index=None``, no BRMaterials."""
        ir = IRModel(
            name="rig",
            bones=[_make_bone("Root")],
            meshes=[_make_mesh("body", parent_bone_index=0)],
        )
        br_meshes, _, br_materials = plan_meshes(ir)
        assert br_meshes[0].material_index is None
        assert br_materials == []

    def test_uv_and_color_layers_copied(self):
        ir = IRModel(
            name="rig",
            bones=[_make_bone("Root")],
            meshes=[_make_mesh(
                "body",
                parent_bone_index=0,
                uv_layers=[IRUVLayer(name='UVMap', uvs=[(0.0, 0.0), (1.0, 1.0)])],
                color_layers=[IRColorLayer(name='Col', colors=[(1, 0, 0, 1)])],
            )],
        )
        br_meshes, _, _ = plan_meshes(ir)
        assert len(br_meshes[0].uv_layers) == 1
        assert br_meshes[0].uv_layers[0].name == 'UVMap'
        assert br_meshes[0].uv_layers[0].uvs == [(0.0, 0.0), (1.0, 1.0)]
        assert len(br_meshes[0].color_layers) == 1
        assert br_meshes[0].color_layers[0].colors == [(1, 0, 0, 1)]
