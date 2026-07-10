"""compose_scene must emit a single scene_data section containing every
model as a ModelSet — SceneData.models is an array, and multi-model files
(map archives) store all models in one section. A per-model scene_data
split breaks round-trips against such files.
"""
from exporter.phases.compose.compose import compose_scene
from shared.IR.scene import IRScene
from shared.IR.skeleton import IRModel, IRBone
from shared.IR.enums import ScaleInheritance
from shared.Nodes.Classes.RootNodes.SceneData import SceneData


def _identity():
    return [[1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0]]


def _make_bone(name, x):
    return IRBone(
        name=name,
        parent_index=None,
        position=(x, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        inverse_bind_matrix=None,
        flags=0,
        is_hidden=False,
        inherit_scale=ScaleInheritance.ALIGNED,
        ik_shrink=False,
        world_matrix=_identity(),
        local_matrix=_identity(),
        normalized_world_matrix=_identity(),
        normalized_local_matrix=_identity(),
        scale_correction=_identity(),
        accumulated_scale=(1.0, 1.0, 1.0),
    )


def _make_model(name, x):
    return IRModel(name=name, bones=[_make_bone(f"{name}_root", x)])


class TestMultiModelSceneData:

    def test_two_models_share_one_scene_data(self):
        scene = IRScene(models=[_make_model("A", 1.0), _make_model("B", 2.0)])
        roots, names = compose_scene(scene)

        assert names == ['scene_data']
        assert isinstance(roots[0], SceneData)
        assert len(roots[0].models) == 2

    def test_model_order_preserved(self):
        scene = IRScene(models=[_make_model("A", 1.0), _make_model("B", 2.0)])
        roots, _ = compose_scene(scene)

        xs = [ms.root_joint.position[0] for ms in roots[0].models]
        # Positions pass through a uniform meters→GC scale, so relative
        # order/proportion is what identifies the models.
        assert xs[0] > 0 and abs(xs[1] / xs[0] - 2.0) < 1e-6

    def test_single_model_still_one_scene_data(self):
        scene = IRScene(models=[_make_model("A", 1.0)])
        roots, names = compose_scene(scene)

        assert names == ['scene_data']
        assert len(roots[0].models) == 1

    def test_boneless_model_skipped(self):
        scene = IRScene(models=[_make_model("A", 1.0), IRModel(name="empty")])
        roots, names = compose_scene(scene)

        assert names == ['scene_data']
        assert len(roots[0].models) == 1

    def test_no_models_no_sections(self):
        roots, names = compose_scene(IRScene())
        assert roots == [] and names == []
