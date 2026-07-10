"""Unit tests for the Plan phase's IR armature → BR armature helper."""
from shared.IR.skeleton import IRBone, IRModel
from shared.IR.enums import ScaleInheritance
from shared.BR.armature import BRArmature, BRBone
from shared.helpers.math_shim import Matrix, matrix_to_list
from importer.phases.plan.helpers.armature import (
    plan_armature,
    choose_inherit_scale,
    choose_tail_offset,
    derive_armature_name,
)


def _make_ir_bone(name, parent_index=None, scale=(1.0, 1.0, 1.0), accumulated=None,
                  ik_shrink=False, is_hidden=False):
    acc = accumulated if accumulated is not None else scale
    identity = matrix_to_list(Matrix.Identity(4))
    return IRBone(
        name=name,
        parent_index=parent_index,
        position=(0.0, 0.0, 0.0),
        rotation=(0.0, 0.0, 0.0),
        scale=scale,
        inverse_bind_matrix=None,
        flags=0,
        is_hidden=is_hidden,
        inherit_scale=ScaleInheritance.ALIGNED,
        ik_shrink=ik_shrink,
        world_matrix=identity,
        local_matrix=identity,
        normalized_world_matrix=identity,
        normalized_local_matrix=identity,
        scale_correction=identity,
        accumulated_scale=acc,
    )


class TestChooseInheritScale:
    """The bake poses every bone; inherit_scale only picks the read-back mode.
    Baked-closure bones read back under NONE, the rest under native ALIGNED."""

    def test_aligned_bone_picks_aligned(self):
        assert choose_inherit_scale(False) == 'ALIGNED'

    def test_baked_bone_picks_none(self):
        assert choose_inherit_scale(True) == 'NONE'


class TestChooseTailOffset:

    def test_default_tail_offset(self):
        bone = _make_ir_bone("B")
        assert choose_tail_offset(bone, ik_hack=False) == (0.0, 0.01, 0.0)

    def test_ik_hack_off_ignores_ik_shrink(self):
        bone = _make_ir_bone("B", ik_shrink=True)
        assert choose_tail_offset(bone, ik_hack=False) == (0.0, 0.01, 0.0)

    def test_ik_hack_on_shrinks_effector_tail(self):
        bone = _make_ir_bone("B", ik_shrink=True, scale=(1.0, 2.0, 1.0))
        tail = choose_tail_offset(bone, ik_hack=True)
        assert tail == (0.0, 1e-4 / 2.0, 0.0)

    def test_ik_hack_on_with_zero_y_scale_falls_back_to_unit(self):
        bone = _make_ir_bone("B", ik_shrink=True, scale=(1.0, 0.0, 1.0))
        tail = choose_tail_offset(bone, ik_hack=True)
        assert tail == (0.0, 1e-4, 0.0)


class TestDeriveArmatureName:

    def test_filename_and_distinct_model_name(self):
        ir = IRModel(name="body")
        options = {"filepath": "/tmp/deoxys.dat"}
        assert derive_armature_name(ir, options, 0) == "deoxys_body_skeleton_0"

    def test_filename_only_when_model_matches(self):
        ir = IRModel(name="deoxys")
        options = {"filepath": "/tmp/deoxys.dat"}
        assert derive_armature_name(ir, options, 3) == "deoxys_skeleton_3"

    def test_no_filepath_fallback(self):
        ir = IRModel(name="rig")
        assert derive_armature_name(ir, {}, 0) == "model_rig_skeleton_0"


class TestPlanArmature:

    def test_single_bone_translation(self):
        ir = IRModel(name="rig", bones=[_make_ir_bone("Root")])
        br = plan_armature(ir, options={"filepath": "test.dat"}, model_index=0)
        assert isinstance(br, BRArmature)
        assert br.name == "test_rig_skeleton_0"
        assert len(br.bones) == 1
        bone = br.bones[0]
        assert isinstance(bone, BRBone)
        assert bone.name == "Root"
        assert bone.parent_index is None
        assert bone.inherit_scale == 'ALIGNED'
        assert bone.rotation_mode == 'XYZ'
        assert bone.tail_offset == (0.0, 0.01, 0.0)

    def test_uniform_bone_aligned_nonuniform_bone_none(self):
        ir = IRModel(name="rig", bones=[
            _make_ir_bone("Uniform", accumulated=(1.0, 1.0, 1.0)),
            _make_ir_bone("NonUniform", accumulated=(1.221, 0.549, 1.0)),
        ])
        br = plan_armature(ir)
        assert br.bones[0].inherit_scale == 'ALIGNED'
        assert br.bones[1].inherit_scale == 'NONE'

    def test_inherit_scale_per_bone_by_accumulated_scale(self):
        """Per-bone decision on accumulated scale. In GX a child inherits
        accumulated scale, so a real descendant of a non-uniform bone is itself
        non-uniform and also bakes."""
        ir = IRModel(name="rig", bones=[
            _make_ir_bone("Root", accumulated=(1.0, 1.0, 1.0)),
            _make_ir_bone("NonUniform", parent_index=0, accumulated=(2.0, 1.0, 0.5)),
            _make_ir_bone("NonUniformChild", parent_index=1, accumulated=(2.0, 1.0, 0.5)),
        ])
        br = plan_armature(ir)
        assert br.bones[0].inherit_scale == 'ALIGNED'
        assert br.bones[1].inherit_scale == 'NONE'
        assert br.bones[2].inherit_scale == 'NONE'

    def test_ik_hack_option_switches_display_and_tail(self):
        ir = IRModel(name="rig", bones=[
            _make_ir_bone("Eff", ik_shrink=True, scale=(1.0, 2.0, 1.0)),
        ])
        br = plan_armature(ir, options={"ik_hack": True})
        assert br.display_type == 'STICK'
        assert br.bones[0].tail_offset == (0.0, 1e-4 / 2.0, 0.0)

    def test_default_matrix_basis_rotates_y_up_to_z_up(self):
        """Blender's Z-up vs GC's Y-up is a π/2 rotation around X."""
        import math
        ir = IRModel(name="rig", bones=[_make_ir_bone("Root")])
        br = plan_armature(ir)
        mb = br.matrix_basis
        assert mb is not None
        # Row 1 (Y axis) should be (0, cos π/2, -sin π/2, 0) = (0, 0, -1, 0)
        assert abs(mb[1][0]) < 1e-9
        assert abs(mb[1][1] - math.cos(math.pi / 2)) < 1e-9
        assert abs(mb[1][2] - (-math.sin(math.pi / 2))) < 1e-9

    def test_parent_relationships_preserved(self):
        ir = IRModel(name="rig", bones=[
            _make_ir_bone("Root"),
            _make_ir_bone("Child", parent_index=0),
            _make_ir_bone("Grandchild", parent_index=1),
        ])
        br = plan_armature(ir)
        assert br.bones[0].parent_index is None
        assert br.bones[1].parent_index == 0
        assert br.bones[2].parent_index == 1

    def test_hidden_flag_propagates(self):
        ir = IRModel(name="rig", bones=[
            _make_ir_bone("Visible"),
            _make_ir_bone("Hidden", is_hidden=True),
        ])
        br = plan_armature(ir)
        assert br.bones[0].is_hidden is False
        assert br.bones[1].is_hidden is True
