"""Tests for phases/describe/bones.py — Joint tree to flat IRBone list."""
import math
import os
import tempfile

from importer.phases.parse.helpers.dat_parser import DATParser
from shared.Nodes.Classes.Joints.Joint import Joint
from shared.IR.skeleton import IRBone
from shared.IR.enums import ScaleInheritance
from importer.phases.describe.helpers.bones import describe_bones, _compile_srt_matrix

from helpers import (
    build_joint, build_dat_with_sections, build_minimal_dat,
    JOINT_SIZE,
)


def _write_dat(data: bytes) -> str:
    fd, path = tempfile.mkstemp(suffix='.dat')
    os.write(fd, data)
    os.close(fd)
    return path


def _parse_joint_tree(data_section, relocations, section_offset=0):
    """Parse a Joint tree from synthetic binary data."""
    dat_bytes = build_dat_with_sections(
        data_section,
        relocations,
        sections=[(section_offset, True)],
        section_names=["test_joint"],
    )
    path = _write_dat(dat_bytes)
    try:
        import io; parser = DATParser(io.BytesIO(open(path, "rb").read()), {"section_names": []})
        joint = Joint(section_offset, None)
        joint.loadFromBinary(parser)
        parser.close()
        return joint
    finally:
        os.unlink(path)


class TestDescribeBonesBasic:

    def test_single_bone(self):
        """A single root joint produces one IRBone."""
        data = build_joint(
            scale=(1.0, 1.0, 1.0),
            rotation=(0.0, 0.0, 0.0),
            position=(0.0, 0.0, 0.0),
        )
        joint = _parse_joint_tree(data, relocations=[])
        bones, _ = describe_bones(joint)

        assert len(bones) == 1
        bone = bones[0]
        assert isinstance(bone, IRBone)
        assert bone.name == "Bone_0"
        assert bone.parent_index is None
        assert bone.position == (0.0, 0.0, 0.0)
        assert bone.scale == (1.0, 1.0, 1.0)
        assert bone.rotation == (0.0, 0.0, 0.0)
        assert bone.inherit_scale == ScaleInheritance.ALIGNED

    def test_single_bone_with_transform(self):
        """Verify position/rotation/scale are preserved."""
        data = build_joint(
            scale=(2.0, 1.0, 0.5),
            rotation=(0.5, 1.0, 1.5),
            position=(10.0, 20.0, 30.0),
        )
        joint = _parse_joint_tree(data, relocations=[])
        bones, _ = describe_bones(joint)

        bone = bones[0]
        assert abs(bone.position[0] - 10.0) < 1e-5
        assert abs(bone.position[1] - 20.0) < 1e-5
        assert abs(bone.position[2] - 30.0) < 1e-5
        assert abs(bone.rotation[0] - 0.5) < 1e-5
        assert abs(bone.scale[0] - 2.0) < 1e-5
        assert abs(bone.scale[2] - 0.5) < 1e-5

    def test_bone_flags_hidden(self):
        """JOBJ_HIDDEN flag sets is_hidden."""
        JOBJ_HIDDEN = 1 << 4
        data = build_joint(flags=JOBJ_HIDDEN, scale=(1, 1, 1))
        joint = _parse_joint_tree(data, relocations=[])
        bones, _ = describe_bones(joint)
        assert bones[0].is_hidden is True

    def test_bone_flags_not_hidden(self):
        data = build_joint(flags=0, scale=(1, 1, 1))
        joint = _parse_joint_tree(data, relocations=[])
        bones, _ = describe_bones(joint)
        assert bones[0].is_hidden is False


class TestDescribeBonesHierarchy:

    def test_parent_child(self):
        """A root with one child produces 2 bones with correct parent_index."""
        child_offset = JOINT_SIZE
        root_data = build_joint(
            child_ptr=child_offset,
            scale=(1.0, 1.0, 1.0),
        )
        child_data = build_joint(
            scale=(1.0, 1.0, 1.0),
            position=(5.0, 0.0, 0.0),
        )
        data = root_data + child_data
        relocations = [8]

        joint = _parse_joint_tree(data, relocations)
        bones, jtb = describe_bones(joint)

        assert len(bones) == 2
        assert bones[0].name == "Bone_0"
        assert bones[0].parent_index is None
        assert bones[1].name == "Bone_1"
        assert bones[1].parent_index == 0
        # Verify joint_to_bone_index mapping
        assert jtb[0] == 0              # root at address 0
        assert jtb[child_offset] == 1   # child at address JOINT_SIZE

    def test_sibling_chain(self):
        """Root with a next sibling — both share None parent."""
        sibling_offset = JOINT_SIZE
        root_data = build_joint(
            next_ptr=sibling_offset,
            scale=(1.0, 1.0, 1.0),
        )
        sibling_data = build_joint(
            scale=(1.0, 1.0, 1.0),
        )
        data = root_data + sibling_data
        # next pointer is at field offset 12 (name=4, flags=4, child=4, next=12)
        relocations = [12]

        joint = _parse_joint_tree(data, relocations)
        bones, _ = describe_bones(joint)

        assert len(bones) == 2
        # Both are roots (no parent)
        assert bones[0].parent_index is None
        assert bones[1].parent_index is None

    def test_three_level_hierarchy(self):
        """Root -> child -> grandchild."""
        child_offset = JOINT_SIZE
        grandchild_offset = 2 * JOINT_SIZE
        root_data = build_joint(child_ptr=child_offset, scale=(1, 1, 1))
        child_data = build_joint(child_ptr=grandchild_offset, scale=(1, 1, 1), position=(1, 0, 0))
        grandchild_data = build_joint(scale=(1, 1, 1), position=(0, 2, 0))
        data = root_data + child_data + grandchild_data
        relocations = [8, JOINT_SIZE + 8]  # child ptrs at offset 8 in each

        joint = _parse_joint_tree(data, relocations)
        bones, _ = describe_bones(joint)

        assert len(bones) == 3
        assert bones[0].parent_index is None  # root
        assert bones[1].parent_index == 0     # child of root
        assert bones[2].parent_index == 1     # grandchild of child


class TestDescribeBonesMatrices:

    def test_identity_world_matrix(self):
        """A root with identity transforms has identity world matrix."""
        data = build_joint(scale=(1, 1, 1), rotation=(0, 0, 0), position=(0, 0, 0))
        joint = _parse_joint_tree(data, relocations=[])
        bones, _ = describe_bones(joint)

        wm = bones[0].world_matrix
        for i in range(4):
            for j in range(4):
                expected = 1.0 if i == j else 0.0
                assert abs(wm[i][j] - expected) < 1e-5, f"wm[{i}][{j}] = {wm[i][j]}, expected {expected}"

    def test_translation_world_matrix(self):
        """Position shows up in world matrix translation column."""
        data = build_joint(scale=(1, 1, 1), position=(3, 4, 5))
        joint = _parse_joint_tree(data, relocations=[])
        bones, _ = describe_bones(joint)

        wm = bones[0].world_matrix
        assert abs(wm[0][3] - 3.0) < 1e-5
        assert abs(wm[1][3] - 4.0) < 1e-5
        assert abs(wm[2][3] - 5.0) < 1e-5

    def test_child_inherits_parent_transform(self):
        """Child world matrix includes parent translation."""
        child_offset = JOINT_SIZE
        root_data = build_joint(child_ptr=child_offset, scale=(1, 1, 1), position=(10, 0, 0))
        child_data = build_joint(scale=(1, 1, 1), position=(5, 0, 0))
        data = root_data + child_data
        relocations = [8]

        joint = _parse_joint_tree(data, relocations)
        bones, _ = describe_bones(joint)

        # Child world position should be 10 + 5 = 15
        child_wm = bones[1].world_matrix
        assert abs(child_wm[0][3] - 15.0) < 1e-5

    def test_accumulated_scale(self):
        """Child accumulated_scale multiplies parent and own scale."""
        child_offset = JOINT_SIZE
        root_data = build_joint(child_ptr=child_offset, scale=(2.0, 3.0, 1.0))
        child_data = build_joint(scale=(0.5, 2.0, 4.0))
        data = root_data + child_data
        relocations = [8]

        joint = _parse_joint_tree(data, relocations)
        bones, _ = describe_bones(joint)

        assert abs(bones[0].accumulated_scale[0] - 2.0) < 1e-5
        assert abs(bones[0].accumulated_scale[1] - 3.0) < 1e-5
        # child: 0.5*2.0=1.0, 2.0*3.0=6.0, 4.0*1.0=4.0
        assert abs(bones[1].accumulated_scale[0] - 1.0) < 1e-5
        assert abs(bones[1].accumulated_scale[1] - 6.0) < 1e-5
        assert abs(bones[1].accumulated_scale[2] - 4.0) < 1e-5


class TestCompileSRTMatrix:

    def test_identity(self):
        """Identity SRT produces identity matrix."""
        from shared.helpers.math_shim import Matrix
        m = _compile_srt_matrix((1, 1, 1), (0, 0, 0), (0, 0, 0))
        for i in range(4):
            for j in range(4):
                expected = 1.0 if i == j else 0.0
                assert abs(m[i][j] - expected) < 1e-6

    def test_translation_only(self):
        m = _compile_srt_matrix((1, 1, 1), (0, 0, 0), (7, 8, 9))
        assert abs(m[0][3] - 7.0) < 1e-6
        assert abs(m[1][3] - 8.0) < 1e-6
        assert abs(m[2][3] - 9.0) < 1e-6

    def test_scale_only(self):
        m = _compile_srt_matrix((2, 3, 4), (0, 0, 0), (0, 0, 0))
        assert abs(m[0][0] - 2.0) < 1e-6
        assert abs(m[1][1] - 3.0) < 1e-6
        assert abs(m[2][2] - 4.0) < 1e-6
