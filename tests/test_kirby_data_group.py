"""Tests for Kirby Air Ride enemy DataGroup parsing.

Layout (decoded from KAR's main.dol — see memory/reference_kar_disassembly.md):
  KirbyDataGroup → variant (slot 0/1/2) → KirbyModelRef → Joint
"""
import io
import struct
import pytest

from helpers import build_archive_header, build_joint, JOINT_SIZE
from importer.phases.parse.helpers.dat_parser import DATParser
from importer.phases.route.route import route_sections
from shared.Nodes.Classes.Joints.Joint import Joint
from shared.Nodes.Classes.Kirby.KirbyDataGroup import KirbyDataGroup
from shared.Nodes.Classes.Kirby.KirbyModelVariant import KirbyModelVariant
from shared.Nodes.Classes.Kirby.KirbyModelRef import KirbyModelRef


MODELREF_SIZE = 0x28   # 40 bytes — see KirbyModelRef.fields
VARIANT_SIZE  = 0x20   # 32 bytes — see KirbyModelVariant.fields
DATAGROUP_SIZE = 0x18  # 24 bytes — see KirbyDataGroup.fields


def _build_modelref(root_joint_ptr=0, joint_count=0):
    """40-byte KirbyModelRef. Only +0x00 (joint) and +0x04 (count) carry data
    in the test fixtures; the rest are zeroed."""
    data  = struct.pack('>I', root_joint_ptr)   # +0x00 root_joint
    data += struct.pack('>I', joint_count)       # +0x04 joint_count
    data += struct.pack('>I', 1)                 # +0x08 flag1
    data += struct.pack('>I', 1)                 # +0x0C flag2
    data += struct.pack('>I', 1)                 # +0x10 flag3
    data += struct.pack('>I', 0)                 # +0x14 anim_set_a
    data += struct.pack('>I', 0)                 # +0x18 anim_set_b
    data += struct.pack('>I', 0)                 # +0x1C anim_set_c
    data += struct.pack('>I', 0)                 # +0x20 pad1
    data += struct.pack('>I', 0)                 # +0x24 pad2
    return data


def _build_variant(model_ptr=0):
    """32-byte KirbyModelVariant. Only +0x08 (model) carries a pointer in the
    fixtures; the other slots are zeroed."""
    data  = struct.pack('>I', 0)                 # +0x00 shared_a
    data += struct.pack('>I', 0)                 # +0x04 shared_b
    data += struct.pack('>I', model_ptr)         # +0x08 model
    data += struct.pack('>I', 0)                 # +0x0C runtime_callbacks
    data += struct.pack('>I', 0)                 # +0x10 common_meta
    data += struct.pack('>I', 0)                 # +0x14 shared_c
    data += struct.pack('>I', 0)                 # +0x18 prev_or_alt
    data += struct.pack('>I', 0)                 # +0x1C end_marker
    return data


def _build_datagroup(variant_a_ptr=0, variant_b_ptr=0, variant_c_ptr=0):
    """24-byte KirbyDataGroup."""
    data  = struct.pack('>I', variant_a_ptr)     # +0x00
    data += struct.pack('>I', variant_b_ptr)     # +0x04
    data += struct.pack('>I', 0)                 # +0x08 aux
    data += struct.pack('>I', 0)                 # +0x0C aux
    data += struct.pack('>I', variant_c_ptr)     # +0x10
    data += struct.pack('>I', 0)                 # +0x14 aux
    return data


def _parse_root(data_section, root_offset):
    """Wrap the data section in a minimal HAL DAT and parse a KirbyDataGroup."""
    header = build_archive_header(len(data_section))
    dat_bytes = header + data_section
    parser = DATParser(io.BytesIO(dat_bytes), {})
    node = KirbyDataGroup(root_offset, None)
    node.loadFromBinary(parser)
    parser.close()
    return node


class TestKirbyDataGroupRouting:

    def test_em_data_group_routes_under_kar(self):
        """Public symbols ending in 'datagroup' route to KirbyDataGroup under
        the Kirby Air Ride rule set."""
        # Build a minimal HAL DAT advertising one section called emCappyDataGroup
        section_name = b'emCappyDataGroup\x00'
        section_info = struct.pack('>II', 0, 0)
        total = 32 + len(section_info) + len(section_name)
        header = struct.pack('>5I', total, 0, 0, 1, 0) + b'\x00' * 12
        dat = header + section_info + section_name
        result = route_sections(dat, game='KIRBY_AIR_RIDE')
        assert result['emCappyDataGroup'] == 'KirbyDataGroup'


class TestKirbyDataGroupParsing:

    def test_three_variants_reach_distinct_joints(self):
        """A DataGroup with three populated variants exposes three Joint roots."""
        # Layout in the data section (offsets are data-relative):
        #   0x00:  KirbyDataGroup (variants point to 0x18, 0x38, 0x58)
        #   0x18:  variant_a → ModelRef at 0x78
        #   0x38:  variant_b → ModelRef at 0xA0
        #   0x58:  variant_c → ModelRef at 0xC8
        #   0x78:  ModelRef A (root_joint = 0xF0, joint_count = 5)
        #   0xA0:  ModelRef B (root_joint = 0x130, joint_count = 7)
        #   0xC8:  ModelRef C (root_joint = 0x170, joint_count = 3)
        #   0xF0:  Joint A (single-node tree)
        #   0x130: Joint B (single-node tree)
        #   0x170: Joint C (single-node tree)
        DG_OFF, VA_OFF, VB_OFF, VC_OFF = 0x00, 0x18, 0x38, 0x58
        MA_OFF, MB_OFF, MC_OFF = 0x78, 0xA0, 0xC8
        JA_OFF, JB_OFF, JC_OFF = 0xF0, 0x130, 0x170

        ds = bytearray(JC_OFF + JOINT_SIZE)
        ds[DG_OFF:DG_OFF+DATAGROUP_SIZE] = _build_datagroup(VA_OFF, VB_OFF, VC_OFF)
        ds[VA_OFF:VA_OFF+VARIANT_SIZE]   = _build_variant(MA_OFF)
        ds[VB_OFF:VB_OFF+VARIANT_SIZE]   = _build_variant(MB_OFF)
        ds[VC_OFF:VC_OFF+VARIANT_SIZE]   = _build_variant(MC_OFF)
        ds[MA_OFF:MA_OFF+MODELREF_SIZE]  = _build_modelref(JA_OFF, 5)
        ds[MB_OFF:MB_OFF+MODELREF_SIZE]  = _build_modelref(JB_OFF, 7)
        ds[MC_OFF:MC_OFF+MODELREF_SIZE]  = _build_modelref(JC_OFF, 3)
        ds[JA_OFF:JA_OFF+JOINT_SIZE] = build_joint(flags=0xAAAA)
        ds[JB_OFF:JB_OFF+JOINT_SIZE] = build_joint(flags=0xBBBB)
        ds[JC_OFF:JC_OFF+JOINT_SIZE] = build_joint(flags=0xCCCC)

        dg = _parse_root(bytes(ds), DG_OFF)

        variants = dg.variants()
        assert len(variants) == 3
        assert all(isinstance(v, KirbyModelVariant) for v in variants)

        joints = dg.root_joints()
        assert len(joints) == 3
        assert all(isinstance(j, Joint) for j in joints)
        assert [j.flags for j in joints] == [0xAAAA, 0xBBBB, 0xCCCC]

        # Joint counts surface from each ModelRef
        assert variants[0].model.joint_count == 5
        assert variants[1].model.joint_count == 7
        assert variants[2].model.joint_count == 3

    def test_only_first_variant_populated(self):
        """A DataGroup whose variant_b/variant_c slots are null exposes a
        single Joint root."""
        DG_OFF = 0x00
        VA_OFF = 0x18
        MA_OFF = 0x40
        JA_OFF = 0x70

        ds = bytearray(JA_OFF + JOINT_SIZE)
        ds[DG_OFF:DG_OFF+DATAGROUP_SIZE] = _build_datagroup(VA_OFF, 0, 0)
        ds[VA_OFF:VA_OFF+VARIANT_SIZE]   = _build_variant(MA_OFF)
        ds[MA_OFF:MA_OFF+MODELREF_SIZE]  = _build_modelref(JA_OFF, 4)
        ds[JA_OFF:JA_OFF+JOINT_SIZE]     = build_joint(flags=0x1234)

        dg = _parse_root(bytes(ds), DG_OFF)

        assert len(dg.variants()) == 1
        joints = dg.root_joints()
        assert len(joints) == 1
        assert joints[0].flags == 0x1234

    def test_variant_without_model_is_skipped(self):
        """A variant whose +0x08 model pointer is null should not surface a
        Joint (game-side this is the 'attached/effect-only' variant kind)."""
        DG_OFF, VA_OFF, VB_OFF = 0x00, 0x18, 0x38
        MA_OFF, JA_OFF = 0x60, 0x90

        ds = bytearray(JA_OFF + JOINT_SIZE)
        ds[DG_OFF:DG_OFF+DATAGROUP_SIZE] = _build_datagroup(VA_OFF, VB_OFF, 0)
        ds[VA_OFF:VA_OFF+VARIANT_SIZE]   = _build_variant(MA_OFF)
        ds[VB_OFF:VB_OFF+VARIANT_SIZE]   = _build_variant(0)            # no model
        ds[MA_OFF:MA_OFF+MODELREF_SIZE]  = _build_modelref(JA_OFF, 2)
        ds[JA_OFF:JA_OFF+JOINT_SIZE]     = build_joint()

        dg = _parse_root(bytes(ds), DG_OFF)

        # Both variant slots populate, but only one yields a joint
        assert len(dg.variants()) == 2
        assert dg.variants()[1].model is None
        assert len(dg.root_joints()) == 1
