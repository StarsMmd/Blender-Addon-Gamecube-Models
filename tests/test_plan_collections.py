"""Unit tests for how the Plan phase files an import into collections.

Object parenting carries the transform but not visibility — only collections
hide their contents — so every import gets a collection of its own, and a
multi-skeleton scene gets one per skeleton.
"""
from shared.IR.scene import IRScene
from shared.IR.skeleton import IRBone, IRModel
from shared.IR.enums import ScaleInheritance
from shared.helpers.math_shim import Matrix, matrix_to_list
from importer.phases.plan.plan import plan_scene
from importer.phases.plan.helpers.armature import derive_scene_name


def _ir_bone(name="Bone_0"):
    identity = matrix_to_list(Matrix.Identity(4))
    return IRBone(
        name=name,
        parent_index=None,
        position=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        inverse_bind_matrix=None,
        flags=0,
        is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED,
        ik_shrink=False,
        world_matrix=identity,
        local_matrix=identity,
        normalized_world_matrix=identity,
        normalized_local_matrix=identity,
        scale_correction=identity,
        accumulated_scale=(1.0, 1.0, 1.0),
    )


def _ir_model(name=""):
    return IRModel(name=name, bones=[_ir_bone()])


def _plan(model_count, filepath="/models/M1_out.dat"):
    scene = IRScene(models=[_ir_model() for _ in range(model_count)])
    return plan_scene(scene, {"filepath": filepath})


class TestSceneName:
    def test_derives_from_the_file_base_name(self):
        assert derive_scene_name({"filepath": "/x/M1_out.dat"}) == "M1_out"

    def test_strips_every_extension(self):
        assert derive_scene_name({"filepath": "/x/room.fdat.dat"}) == "room"

    def test_falls_back_when_there_is_no_filepath(self):
        assert derive_scene_name({}) == "model"
        assert derive_scene_name(None) == "model"


class TestSceneCollection:
    def test_scene_is_named_after_the_file(self):
        assert _plan(1).collection_name == "M1_out"

    def test_named_even_when_the_scene_has_no_models(self):
        plan = plan_scene(IRScene(), {"filepath": "/x/M1_out.dat"})

        assert plan.collection_name == "M1_out"
        assert plan.models == []


class TestPerSkeletonCollections:
    def test_a_lone_skeleton_gets_no_subcollection(self):
        plan = _plan(1)

        assert plan.models[0].collection_name is None

    def test_several_skeletons_each_get_one_named_after_the_armature(self):
        plan = _plan(3)

        assert [model.collection_name for model in plan.models] == [
            "M1_out_skeleton_0", "M1_out_skeleton_1", "M1_out_skeleton_2"]
        assert [model.armature.name for model in plan.models] == [
            model.collection_name for model in plan.models]

    def test_named_models_keep_their_name_in_the_subcollection(self):
        scene = IRScene(models=[_ir_model("body"), _ir_model("wheel")])

        plan = plan_scene(scene, {"filepath": "/x/M1_out.dat"})

        assert [model.collection_name for model in plan.models] == [
            "M1_out_body_skeleton_0", "M1_out_wheel_skeleton_1"]
