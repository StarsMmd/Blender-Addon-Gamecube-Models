"""Regression test: JOBJ_INSTANCE mesh copies must be static duplicates.

Background: an instance copy shares the one armature with the mesh it clones.
If the copy kept an armature modifier, posing the template's bones (any imported
action) would re-deform every copy about the template's bone locations instead of
the copy's own — flinging weighted geometry off-model. Map palm/tree instances
weighted to animated frond bones vanished this way, leaving only the original and
the copies of un-animated parts (foundations). The copy is placed purely by
matrix_local, so build must strip its armature modifier(s).
"""
from unittest.mock import MagicMock, patch

from importer.phases.build_blender.helpers.meshes import build_meshes
from shared.BR.scene import BRModel
from shared.BR.meshes import BRMeshInstance


def _mesh_obj_with_armature_modifier():
    obj = MagicMock()
    arm_mod = MagicMock()
    arm_mod.type = 'ARMATURE'
    other_mod = MagicMock()
    other_mod.type = 'EDGE_SPLIT'
    obj.modifiers = [arm_mod, other_mod]
    obj.copy.return_value = _copied(obj)
    return obj


def _copied(source):
    copy = MagicMock()
    # A real object.copy() carries the modifier stack over to the copy.
    arm_mod = MagicMock(); arm_mod.type = 'ARMATURE'
    other_mod = MagicMock(); other_mod.type = 'EDGE_SPLIT'
    copy.modifiers = _RemovableList([arm_mod, other_mod])
    return copy


class _RemovableList(list):
    """Minimal stand-in for bpy's modifier collection with .remove()."""
    def remove(self, item):
        super().remove(item)


def _run_build(model, original):
    with patch(
        "importer.phases.build_blender.helpers.meshes.bpy"
    ) as bpy_mock, patch(
        "importer.phases.build_blender.helpers.meshes.Matrix",
        side_effect=lambda x: x,
    ), patch(
        "importer.phases.build_blender.helpers.meshes._build_mesh",
        return_value=original,
    ):
        bpy_mock.context.scene.collection.objects.link = MagicMock()
        build_meshes(model, MagicMock(), context=MagicMock(), logger=MagicMock())


def _model_with_one_instance():
    return BRModel(
        name="rig",
        armature=MagicMock(),
        meshes=[MagicMock(material_index=None, id="m0")],
        mesh_instances=[BRMeshInstance(
            source_mesh_index=0,
            target_parent_bone_name="Instance",
            matrix_local=[[1, 0, 0, 5], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
        )],
        materials=[],
    )


def test_instance_copy_has_armature_modifier_stripped():
    original = _mesh_obj_with_armature_modifier()
    copy = original.copy.return_value

    _run_build(_model_with_one_instance(), original)

    # The armature modifier is gone; the unrelated modifier survives.
    remaining = [m.type for m in copy.modifiers]
    assert 'ARMATURE' not in remaining, "instance copy must have no armature modifier"
    assert remaining == ['EDGE_SPLIT']


def test_instance_offset_is_baked_into_private_geometry():
    """The placement is baked into the copy's own mesh data (so the object
    arrives at identity), not left as a live matrix_local for post-process to
    preserve. The copy must not share the original's datablock."""
    original = _mesh_obj_with_armature_modifier()
    copy = original.copy.return_value
    shared_data = copy.data  # datablock object.copy() shares with the original
    model = _model_with_one_instance()

    _run_build(model, original)

    # A private datablock was made and the instance matrix baked into it.
    shared_data.copy.assert_called_once()
    assert copy.data is shared_data.copy.return_value  # reassigned to private copy
    copy.data.transform.assert_called_once_with(model.mesh_instances[0].matrix_local)
