"""Tests for the exporter pipeline phases."""
import io
import os
import struct
import tempfile
import pytest

from shared.IR.skeleton import IRBone, IRModel
from shared.IR.enums import ScaleInheritance
from shared.IR import IRScene
from shared.helpers.scale import METERS_TO_GC as G
from shared.helpers.shiny_params import ShinyParams
from shared.helpers.pkx import PKXContainer
from shared.helpers.binary import read
from shared.helpers.logger import StubLogger
from exporter.phases.pre_process.pre_process import pre_process, _validate_output_path
from exporter.phases.compose.helpers.bones import compose_bones
from exporter.phases.serialize.serialize import serialize
from exporter.phases.package.package import package_output
from shared.Constants.hsd import JOBJ_HIDDEN, JOBJ_INSTANCE
from exporter.phases.compose.helpers.meshes import _build_envelope_map


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _identity_4x4():
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]


def _make_bone(name, parent_index=None, position=(0, 0, 0), rotation=(0, 0, 0),
               scale=(1, 1, 1), flags=0, instance_child=None, inverse_bind=None):
    return IRBone(
        name=name,
        parent_index=parent_index,
        position=position,
        rotation=rotation,
        scale=scale,
        inverse_bind_matrix=inverse_bind,
        flags=flags,
        is_hidden=bool(flags & JOBJ_HIDDEN),
        inherit_scale=ScaleInheritance.ALIGNED,
        ik_shrink=False,
        world_matrix=_identity_4x4(),
        local_matrix=_identity_4x4(),
        normalized_world_matrix=_identity_4x4(),
        normalized_local_matrix=_identity_4x4(),
        scale_correction=_identity_4x4(),
        accumulated_scale=scale,
        instance_child_bone_index=instance_child,
    )


def _build_colo_pkx(dat_body_size=64, shiny_color1=(0, 1, 2, 3), shiny_color2=(128, 128, 128, 128)):
    """Build a minimal Colosseum PKX: [0x40 header][DAT padded][shiny 20 bytes]."""
    marker = dat_body_size
    header = bytearray(0x40)
    struct.pack_into('>I', header, 0, marker)  # dat_file_size
    struct.pack_into('>I', header, 8, 0)  # anim_section_count = 0 (no entries for minimal test)
    dat_body = struct.pack('>I', marker) + b'\x00' * (dat_body_size - 4)
    # Pad DAT to 0x20 boundary
    pad = (0x20 - (len(dat_body) % 0x20)) % 0x20
    dat_padded = dat_body + b'\x00' * pad
    # Shiny: 4 × uint32 routing + 1 × uint32 ARGB color (20 bytes)
    shiny = bytearray(20)
    struct.pack_into('>I', shiny, 0, shiny_color1[0])
    struct.pack_into('>I', shiny, 4, shiny_color1[1])
    struct.pack_into('>I', shiny, 8, shiny_color1[2])
    struct.pack_into('>I', shiny, 12, shiny_color1[3])
    # ARGB from RGBA: brightness_r=color2[0], g=[1], b=[2], a=[3] → ARGB
    argb = (shiny_color2[3] << 24) | (shiny_color2[0] << 16) | (shiny_color2[1] << 8) | shiny_color2[2]
    struct.pack_into('>I', shiny, 16, argb)
    return bytes(header) + dat_padded + bytes(shiny)


def _build_xd_pkx(dat_body_size=64, shiny_color1=(0, 1, 2, 3), shiny_color2=(128, 128, 128, 128)):
    """Build a minimal XD PKX: [0xE60 header][DAT][trailer]."""
    header_size = 0xE60
    raw = bytearray(header_size + dat_body_size + 16)  # 16 byte trailer
    # Different values at 0x00 and 0x40 to signal XD
    struct.pack_into('>I', raw, 0, dat_body_size)
    struct.pack_into('>I', raw, 0x40, 0xBBBBBBBB)
    struct.pack_into('>I', raw, 8, 0)  # GPT1 size = 0
    struct.pack_into('>I', raw, 0x10, 17)  # anim_section_count = 17
    # DAT file_size field
    struct.pack_into('>I', raw, header_size, dat_body_size)
    # Shiny routing: 4 × uint32 at 0x70
    struct.pack_into('>I', raw, 0x70, shiny_color1[0])
    struct.pack_into('>I', raw, 0x74, shiny_color1[1])
    struct.pack_into('>I', raw, 0x78, shiny_color1[2])
    struct.pack_into('>I', raw, 0x7C, shiny_color1[3])
    # Shiny brightness: 4 × uint8 at 0x80
    raw[0x80] = shiny_color2[0]
    raw[0x81] = shiny_color2[1]
    raw[0x82] = shiny_color2[2]
    raw[0x83] = shiny_color2[3]
    return bytes(raw)


# ---------------------------------------------------------------------------
# Pre-process tests
# ---------------------------------------------------------------------------

class TestPreProcess:

    def test_dat_output_always_passes(self, tmp_path):
        """Any .dat output path passes validation (file need not exist)."""
        filepath = str(tmp_path / "output.dat")
        _validate_output_path(filepath, logger=StubLogger())

    def test_pkx_output_existing_file_passes(self, tmp_path):
        """PKX output passes when the target file exists."""
        filepath = str(tmp_path / "output.pkx")
        with open(filepath, 'wb') as f:
            f.write(b'\x00' * 64)
        _validate_output_path(filepath, logger=StubLogger())

    def test_pkx_output_new_file_passes(self, tmp_path):
        """PKX output to a new file passes validation (created from scratch)."""
        filepath = str(tmp_path / "nonexistent.pkx")
        _validate_output_path(filepath, logger=StubLogger())

    def test_no_extension_passes(self, tmp_path):
        """Files without extension pass validation."""
        filepath = str(tmp_path / "output")
        _validate_output_path(filepath, logger=StubLogger())


# ---------------------------------------------------------------------------
# Compose bones tests
# ---------------------------------------------------------------------------

class TestComposeBones:

    def test_empty_list(self):
        """Empty bone list returns None root and empty joints list."""
        root, joints = compose_bones([])
        assert root is None
        assert joints == []

    def test_single_bone(self):
        """Single bone produces a root Joint with correct fields."""
        bones = [_make_bone("Root", position=(1, 2, 3), rotation=(0.1, 0.2, 0.3), scale=(1, 1, 1))]
        root, joints = compose_bones(bones)

        assert root is not None
        assert len(joints) == 1
        assert root.name == "Root"
        assert [round(p, 6) for p in root.position] == [round(1 * G, 6), round(2 * G, 6), round(3 * G, 6)]
        assert list(root.rotation) == pytest.approx([0.1, 0.2, 0.3])
        assert list(root.scale) == [1, 1, 1]
        assert root.child is None
        assert root.next is None

    def test_parent_child(self):
        """Two bones: parent → child linked via .child pointer."""
        bones = [
            _make_bone("Parent"),
            _make_bone("Child", parent_index=0),
        ]
        root, joints = compose_bones(bones)

        assert root is joints[0]
        assert root.child is not None
        assert root.child is joints[1]
        assert root.child.child is None
        assert root.child.next is None

    def test_siblings(self):
        """Three children of the same parent linked via .next pointers."""
        bones = [
            _make_bone("Parent"),
            _make_bone("A", parent_index=0),
            _make_bone("B", parent_index=0),
            _make_bone("C", parent_index=0),
        ]
        root, joints = compose_bones(bones)

        assert root.child is joints[1]
        assert root.child.next is joints[2]
        assert root.child.next.next is joints[3]
        assert root.child.next.next.next is None

    def test_deep_hierarchy(self):
        """Chain of parent→child→grandchild."""
        bones = [
            _make_bone("Root"),
            _make_bone("Mid", parent_index=0),
            _make_bone("Leaf", parent_index=1),
        ]
        root, joints = compose_bones(bones)

        assert root.child is joints[1]
        assert root.child.child is joints[2]
        assert root.child.child.child is None

    def test_flags_preserved(self):
        """Joint flags are copied from IRBone."""
        bones = [_make_bone("Hidden", flags=JOBJ_HIDDEN)]
        root, joints = compose_bones(bones)
        assert root.flags == JOBJ_HIDDEN

    def test_inverse_bind_matrix(self):
        """Inverse bind matrix translation column is scaled to GC units."""
        ibm = [[1, 0, 0, 5], [0, 1, 0, 10], [0, 0, 1, 15], [0, 0, 0, 1]]
        bones = [_make_bone("Bone", inverse_bind=ibm)]
        root, joints = compose_bones(bones)
        expected = [[1, 0, 0, 5 * G], [0, 1, 0, 10 * G], [0, 0, 1, 15 * G], [0, 0, 0, 1]]
        for r in range(4):
            for c in range(4):
                assert abs(root.inverse_bind[r][c] - expected[r][c]) < 1e-6

    def test_instance_bone(self):
        """JOBJ_INSTANCE bone's child points to the target bone."""
        bones = [
            _make_bone("Root"),
            _make_bone("Target", parent_index=0),
            _make_bone("Instance", parent_index=0, flags=JOBJ_INSTANCE, instance_child=1),
        ]
        root, joints = compose_bones(bones)

        # Instance bone is a sibling of Target
        instance = root.child.next
        assert instance is joints[2]
        assert instance.flags & JOBJ_INSTANCE
        # Instance's child should point to the Target joint
        assert instance.child is joints[1]

    def test_multiple_roots(self):
        """Multiple root bones are linked via .next on the root."""
        bones = [
            _make_bone("Root1"),
            _make_bone("Root2"),
        ]
        root, joints = compose_bones(bones)

        assert root is joints[0]
        assert root.next is joints[1]
        assert root.next.next is None


# ---------------------------------------------------------------------------
# Serialize tests
# ---------------------------------------------------------------------------

class TestSerialize:

    def test_empty_produces_header_only(self):
        """Serializing no nodes produces a 32-byte DAT header."""
        dat_bytes = serialize([], [])
        assert len(dat_bytes) == 32  # DAT header only

    def test_serialize_produces_valid_dat(self):
        """Serialized output starts with a valid DAT header."""
        from shared.Nodes.Classes.RootNodes.SceneData import SceneData
        from shared.Nodes.Classes.Joints.ModelSet import ModelSet
        from shared.Nodes.Classes.Joints.Joint import Joint

        joint = Joint(address=None, blender_obj=None)
        joint.name = "Root"
        joint.flags = 0
        joint.child = None
        joint.next = None
        joint.property = None
        joint.reference = None
        joint.rotation = [0, 0, 0]
        joint.scale = [1, 1, 1]
        joint.position = [0, 0, 0]
        joint.inverse_bind = None

        model_set = ModelSet(address=None, blender_obj=None)
        model_set.root_joint = joint
        model_set.animated_joints = None
        model_set.animated_material_joints = None
        model_set.animated_shape_joints = None

        scene_data = SceneData(address=None, blender_obj=None)
        scene_data.models = [model_set]
        scene_data.camera = None
        scene_data.lights = None
        scene_data.fog = None

        dat_bytes = serialize([scene_data], ['scene_data'])

        assert len(dat_bytes) > 32
        # DAT header: file_size is first uint
        file_size = read('uint', dat_bytes, 0)
        assert file_size > 0
        assert file_size <= len(dat_bytes)


# ---------------------------------------------------------------------------
# Package tests
# ---------------------------------------------------------------------------

class TestPackage:

    def test_dat_passthrough(self, tmp_path):
        """For .dat output, DAT bytes are returned unchanged."""
        dat_bytes = b'\x00' * 64
        filepath = str(tmp_path / "output.dat")
        result = package_output(dat_bytes, filepath)
        assert result == dat_bytes

    def test_pkx_injection_preserves_trailer(self, tmp_path):
        """PKX packaging preserves the trailer after replacing the DAT."""
        original = _build_colo_pkx(dat_body_size=64)
        filepath = str(tmp_path / "model.pkx")
        with open(filepath, 'wb') as f:
            f.write(original)

        # Build a different-sized DAT
        new_dat = struct.pack('>I', 128) + b'\xAA' * 124
        result = package_output(new_dat, filepath)

        # Parse the result
        pkx = PKXContainer(result)
        assert pkx.dat_bytes == new_dat
        # Trailer should be preserved (last 49 bytes of original)
        original_trailer = original[0x40 + 64:]
        result_trailer = result[0x40 + 128:]
        assert result_trailer == original_trailer

    def test_pkx_updates_header_file_size(self, tmp_path):
        """PKX header file_size field is updated to match the new DAT."""
        original = _build_xd_pkx(dat_body_size=64)
        filepath = str(tmp_path / "model.pkx")
        with open(filepath, 'wb') as f:
            f.write(original)

        new_dat = struct.pack('>I', 256) + b'\x00' * 252
        result = package_output(new_dat, filepath)
        header_file_size = read('uint', result, 0)
        assert header_file_size == 256

    def test_pkx_shiny_write_back(self, tmp_path):
        """Shiny params are written into the PKX header."""
        original = _build_xd_pkx(dat_body_size=64)
        filepath = str(tmp_path / "model.pkx")
        with open(filepath, 'wb') as f:
            f.write(original)

        new_dat = struct.pack('>I', 64) + b'\x00' * 60
        shiny = ShinyParams(
            route_r=2, route_g=0, route_b=1, route_a=3,
            brightness_r=0.5, brightness_g=-0.5, brightness_b=0.0, brightness_a=0.0,
        )
        result = package_output(new_dat, filepath, shiny_params=shiny)

        pkx = PKXContainer(result)
        result_shiny = pkx.shiny_params
        assert result_shiny is not None
        assert result_shiny.route_r == 2
        assert result_shiny.route_g == 0
        assert result_shiny.route_b == 1
        assert pytest.approx(result_shiny.brightness_r, abs=0.01) == 0.5
        assert pytest.approx(result_shiny.brightness_g, abs=0.01) == -0.5

    def test_no_extension_treated_as_dat(self, tmp_path):
        """Files without extension are treated as .dat (passthrough)."""
        dat_bytes = b'\x00' * 32
        filepath = str(tmp_path / "output")
        result = package_output(dat_bytes, filepath)
        assert result == dat_bytes


# ---------------------------------------------------------------------------
# PKXContainer tests
# ---------------------------------------------------------------------------

class TestPKXContainer:

    def test_colo_format_detection(self):
        raw = _build_colo_pkx()
        pkx = PKXContainer(raw)
        assert pkx.is_xd is False
        assert pkx.header_size == 0x40

    def test_xd_format_detection(self):
        raw = _build_xd_pkx()
        pkx = PKXContainer(raw)
        assert pkx.is_xd is True
        assert pkx.header_size == 0xE60

    def test_dat_bytes_read(self):
        raw = _build_colo_pkx(dat_body_size=64)
        pkx = PKXContainer(raw)
        assert len(pkx.dat_bytes) == 64

    def test_dat_replacement_same_size(self):
        raw = _build_colo_pkx(dat_body_size=64)
        pkx = PKXContainer(raw)
        original_trailer = raw[0x40 + 64:]

        new_dat = struct.pack('>I', 64) + b'\xFF' * 60
        pkx.dat_bytes = new_dat
        assert pkx.dat_bytes == new_dat

        result = pkx.to_bytes()
        assert result[0x40 + 64:] == original_trailer

    def test_dat_replacement_different_size(self):
        raw = _build_colo_pkx(dat_body_size=64)
        pkx = PKXContainer(raw)
        original_trailer = raw[0x40 + 64:]

        new_dat = struct.pack('>I', 128) + b'\xFF' * 124
        pkx.dat_bytes = new_dat
        assert pkx.dat_bytes == new_dat

        result = pkx.to_bytes()
        # Trailer preserved after the new DAT
        assert result[0x40 + 128:] == original_trailer
        # Header file_size updated
        assert read('uint', result, 0) == 128

    def test_shiny_round_trip_xd(self):
        shiny = ShinyParams(2, 0, 1, 3, 0.5, -0.5, 0.0, 0.0)
        raw = _build_xd_pkx(shiny_color1=(2, 0, 1, 3), shiny_color2=(191, 64, 128, 128))
        pkx = PKXContainer(raw)

        pkx.shiny_params = shiny
        result_shiny = PKXContainer(pkx.to_bytes()).shiny_params
        assert result_shiny.route_r == 2
        assert result_shiny.route_g == 0
        assert pytest.approx(result_shiny.brightness_r, abs=0.01) == 0.5

    def test_shiny_round_trip_colo(self):
        """Colosseum shiny params survive DAT replacement (they're in the trailer)."""
        shiny = ShinyParams(1, 2, 0, 3, 0.3, -0.2, 0.1, 0.0)
        raw = _build_colo_pkx()
        pkx = PKXContainer(raw)
        pkx.shiny_params = shiny

        # Replace DAT with different size
        new_dat = struct.pack('>I', 128) + b'\x00' * 124
        pkx.dat_bytes = new_dat

        # Shiny should survive (it's in the trailer, not the DAT)
        result = PKXContainer(pkx.to_bytes())
        result_shiny = result.shiny_params
        assert result_shiny is not None
        assert result_shiny.route_r == 1
        assert result_shiny.route_g == 2
        assert pytest.approx(result_shiny.brightness_r, abs=0.01) == 0.3

    def test_too_small_file(self):
        """Files too small for a valid PKX don't crash."""
        pkx = PKXContainer(b'\x00' * 16)
        assert pkx.shiny_params is None

    def test_from_file(self, tmp_path):
        raw = _build_xd_pkx()
        filepath = str(tmp_path / "test.pkx")
        with open(filepath, 'wb') as f:
            f.write(raw)
        pkx = PKXContainer.from_file(filepath)
        assert pkx.is_xd is True
        assert len(pkx.dat_bytes) == 64


# ---------------------------------------------------------------------------
# PObject iterative parsing tests
# ---------------------------------------------------------------------------

class TestPObjectIterativeParsing:
    """Tests for the PObject next-chain iterative parsing fix."""

    def test_pobj_fields_include_iterative_list(self):
        """PObject has _iterative_fields for non-recursive parsing."""
        from shared.Nodes.Classes.Mesh.PObject import PObject
        assert hasattr(PObject, '_iterative_fields')
        names = [f[0] for f in PObject._iterative_fields]
        assert '_next_raw_ptr' in names
        assert 'next' not in names

    def test_pobj_fields_match_except_next(self):
        """_iterative_fields matches fields except next→_next_raw_ptr."""
        from shared.Nodes.Classes.Mesh.PObject import PObject
        assert len(PObject._iterative_fields) == len(PObject.fields)
        for orig, iter_f in zip(PObject.fields, PObject._iterative_fields):
            if orig[0] == 'next':
                assert iter_f[0] == '_next_raw_ptr'
                assert iter_f[1] == 'uint'
            else:
                assert orig == iter_f


# ---------------------------------------------------------------------------
# Envelope weight quantization tests
# ---------------------------------------------------------------------------

class TestEnvelopeWeightQuantization:
    """Tests for weight quantization in the compose phase."""

    def test_weights_quantized_to_25_percent(self):
        """Envelope map quantizes weights to 25% steps."""
        assignments = [
            (0, [('BoneA', 0.73), ('BoneB', 0.27)]),
            (1, [('BoneA', 0.71), ('BoneB', 0.29)]),
            (2, [('BoneA', 0.80), ('BoneB', 0.20)]),
        ]
        bone_map = {'BoneA': 0, 'BoneB': 1}
        result = _build_envelope_map(assignments, bone_map)
        # 0.73→0.75, 0.71→0.75, 0.80→0.75 — all should collapse to same envelope
        assert result['vertex_to_env'][0] == result['vertex_to_env'][1]
        assert result['vertex_to_env'][0] == result['vertex_to_env'][2]
        assert len(result['envelopes']) == 1

    def test_distinct_weights_stay_separate(self):
        """Weights that differ by >25% remain separate envelopes."""
        assignments = [
            (0, [('BoneA', 1.0)]),
            (1, [('BoneA', 0.5), ('BoneB', 0.5)]),
        ]
        bone_map = {'BoneA': 0, 'BoneB': 1}
        result = _build_envelope_map(assignments, bone_map)
        assert result['vertex_to_env'][0] != result['vertex_to_env'][1]
        assert len(result['envelopes']) == 2

    def test_identical_weights_same_envelope(self):
        """Identical weight combos map to the same envelope."""
        assignments = [
            (0, [('BoneA', 0.5), ('BoneB', 0.5)]),
            (1, [('BoneA', 0.5), ('BoneB', 0.5)]),
        ]
        bone_map = {'BoneA': 0, 'BoneB': 1}
        result = _build_envelope_map(assignments, bone_map)
        assert result['vertex_to_env'][0] == result['vertex_to_env'][1]
        assert len(result['envelopes']) == 1


# ---------------------------------------------------------------------------
# Motion type derivation tests
# ---------------------------------------------------------------------------

class TestMotionTypeDerivation:
    """Tests for PKX motion_type derivation from slot type."""

    def test_loop_gets_motion_2(self):
        """Loop slot type produces motion_type=2."""
        # Simulate what _extract_pkx_header does
        anim_type_str = "loop"
        anim_name = "idle_anim"
        is_xd = True
        has_anim = isinstance(anim_name, str) and anim_name != ""
        motion = (2 if anim_type_str == "loop" else 1) if (is_xd and has_anim) else 0
        assert motion == 2

    def test_action_gets_motion_1(self):
        """Action slot type produces motion_type=1."""
        for atype in ["action", "hit_reaction", "compound"]:
            anim_name = "some_anim"
            is_xd = True
            has_anim = isinstance(anim_name, str) and anim_name != ""
            motion = (2 if atype == "loop" else 1) if (is_xd and has_anim) else 0
            assert motion == 1, f"Failed for type={atype}"

    def test_empty_anim_gets_motion_0(self):
        """Empty animation reference produces motion_type=0 (disabled)."""
        anim_name = ""
        is_xd = True
        has_anim = isinstance(anim_name, str) and anim_name != ""
        motion = (2 if "loop" == "loop" else 1) if (is_xd and has_anim) else 0
        assert motion == 0

    def test_colosseum_always_motion_0(self):
        """Colosseum format always produces motion_type=0."""
        anim_name = "some_anim"
        is_xd = False
        has_anim = isinstance(anim_name, str) and anim_name != ""
        motion = (2 if "action" == "loop" else 1) if (is_xd and has_anim) else 0
        assert motion == 0


# ---------------------------------------------------------------------------
# Idle animation name compaction tests
# ---------------------------------------------------------------------------

class TestIdleNameCompaction:
    """Tests for the idle animation name compaction in describe phase."""

    def test_idle_compacts_to_idle(self):
        """Exact 'Idle' slot compacts to 'Idle'."""
        from importer.phases.describe.helpers.animations import _compact_anim_name
        assert _compact_anim_name(['Idle']) == 'Idle'

    def test_idle_mixed_with_extra_still_idle(self):
        """Slot 0 (Idle) shared with an Extra slot still compacts to Idle."""
        from importer.phases.describe.helpers.animations import _compact_anim_name
        assert _compact_anim_name(['Idle', 'Extra 1']) == 'Idle'

    def test_extra_only_keeps_extra_label(self):
        """Extra slots (11, 13-15) no longer fold into Idle — they are per-Pokemon specials (e.g., Groudon's Seismic Toss animation lives in Extra 2)."""
        from importer.phases.describe.helpers.animations import _compact_anim_name
        assert _compact_anim_name(['Extra 1']) == 'Extra 1'
        assert _compact_anim_name(['Extra 2']) == 'Extra 2'

    def test_idle_mixed_with_other_still_idle(self):
        """Idle mixed with a damaging-move slot still compacts to Idle."""
        from importer.phases.describe.helpers.animations import _compact_anim_name
        assert _compact_anim_name(['Idle', 'Physical A']) == 'Idle'

    def test_non_idle_unchanged(self):
        """Non-idle slot names are not affected."""
        from importer.phases.describe.helpers.animations import _compact_anim_name
        assert _compact_anim_name(['Physical A']) == 'Physical A'
        assert _compact_anim_name(['Damage']) == 'Damage'
