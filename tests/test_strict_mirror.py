"""Tests for Strict Mirror Mode (importer/phases/describe/helpers/strictness.py).

Strict Mirror Mode makes the importer raise on fault classes the game engine
cannot tolerate, instead of silently healing them. These tests cover:

- L1: >10 envelope weights per vertex
- L2: missing PNMTXIDX on envelope-typed PObj
- L3: unknown camera projection_flags
"""
from types import SimpleNamespace

import pytest

from shared.helpers.math_shim import Matrix
from shared.helpers.logger import StubLogger
from shared.Constants.hsd import POBJ_ENVELOPE
from shared.Constants.gx import GX_VA_PNMTXIDX, GX_VA_POS
from importer.phases.describe.helpers.strictness import StrictMirrorError
from importer.phases.describe.helpers.meshes import _extract_envelope_weights
from importer.phases.describe.helpers.cameras import describe_camera


# ---------------------------------------------------------------------------
# Mock helpers (mirror test_describe_envelope.py conventions)
# ---------------------------------------------------------------------------

def _make_bone(name='bone', flags=0):
    return SimpleNamespace(
        name=name,
        flags=flags,
        world_matrix=[list(row) for row in Matrix.Identity(4)],
        inverse_bind_matrix=None,
        parent_index=None,
        mesh_indices=[],
    )


def _make_envelope_entry(weight, joint_address):
    joint = SimpleNamespace(address=joint_address)
    return SimpleNamespace(weight=weight, joint=joint)


def _make_envelope(entry_count):
    entries = [_make_envelope_entry(1.0 / entry_count, 0x1000 + i)
               for i in range(entry_count)]
    return SimpleNamespace(envelopes=entries)


def _make_pobj(envelope_list, include_pnmtxidx=True, address=0xABCD):
    if include_pnmtxidx:
        vtx_pnmtx = SimpleNamespace(attribute=GX_VA_PNMTXIDX)
        vtx_pos = SimpleNamespace(attribute=GX_VA_POS)
        vertex_list = SimpleNamespace(vertices=[vtx_pnmtx, vtx_pos])
        # env_source values are pnmtxidx*3; all three verts reference envelope 0
        sources = {0: [0, 0, 0], 1: []}
        face_lists = {0: [[0, 1, 2]], 1: [[0, 1, 2]]}
    else:
        # Envelope-typed PObj with no PNMTXIDX — should raise in strict mode
        vtx_pos = SimpleNamespace(attribute=GX_VA_POS)
        vertex_list = SimpleNamespace(vertices=[vtx_pos])
        sources = {0: []}
        face_lists = {0: [[0, 1, 2]]}

    return SimpleNamespace(
        address=address,
        vertex_list=vertex_list,
        property=envelope_list,
        flags=POBJ_ENVELOPE,
        sources=sources,
        face_lists=face_lists,
    )


def _make_camera(perspective_flags=1, position=(0.0, 0.0, 10.0),
                 interest=(0.0, 0.0, 0.0), near=0.1, far=1000.0):
    pos_node = SimpleNamespace(position=position) if position is not None else None
    int_node = SimpleNamespace(position=interest) if interest is not None else None
    return SimpleNamespace(
        name=None,
        flags=0,
        perspective_flags=perspective_flags,
        position=pos_node,
        interest=int_node,
        roll=0.0,
        near=near,
        far=far,
        field_of_view=30.0,
        aspect=1.33,
    )


# ---------------------------------------------------------------------------
# L1: Envelope weight cap
# ---------------------------------------------------------------------------

class TestEnvelopeCap:
    def _run(self, weight_count, strict):
        pobj = _make_pobj([_make_envelope(weight_count)])
        bones = [_make_bone()]
        jtb = {0x1000 + i: 0 for i in range(weight_count)}
        faces = [[0, 1, 2]]
        verts = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
        logger = StubLogger()
        options = {"strict_mirror": True} if strict else {}
        return _extract_envelope_weights(
            pobj, None, 0, bones, jtb, faces, verts, None, None, logger, options
        )

    def test_under_cap_lenient_ok(self):
        # 10 weights = exactly the cap, no leniency triggered
        self._run(weight_count=10, strict=False)

    def test_under_cap_strict_ok(self):
        self._run(weight_count=10, strict=True)

    def test_over_cap_lenient_passes(self):
        # Game would choke but importer heals silently
        self._run(weight_count=11, strict=False)

    def test_over_cap_strict_raises(self):
        with pytest.raises(StrictMirrorError, match="envelope_over_cap"):
            self._run(weight_count=11, strict=True)


# ---------------------------------------------------------------------------
# L2: Missing PNMTXIDX on envelope PObj
# ---------------------------------------------------------------------------

class TestMissingPnmtxidx:
    def _run(self, strict):
        pobj = _make_pobj([_make_envelope(2)], include_pnmtxidx=False)
        bones = [_make_bone()]
        logger = StubLogger()
        options = {"strict_mirror": True} if strict else {}
        return _extract_envelope_weights(
            pobj, None, 0, bones, {}, [[0, 1, 2]], [(0, 0, 0)], None, None, logger, options
        )

    def test_lenient_falls_back_to_rigid(self):
        result = self._run(strict=False)
        # Lenient mode keeps current behavior — returns a RIGID fallback.
        from shared.IR.enums import SkinType
        assert result.type == SkinType.RIGID

    def test_strict_raises(self):
        with pytest.raises(StrictMirrorError, match="envelope_no_pnmtxidx"):
            self._run(strict=True)


# ---------------------------------------------------------------------------
# L3: Camera unknown projection / missing eye / target
# ---------------------------------------------------------------------------

class TestCameraStrictness:
    def test_unknown_projection_lenient_returns_none(self):
        cam = _make_camera(perspective_flags=0)
        assert describe_camera(cam, 0) is None

    def test_unknown_projection_strict_raises(self):
        cam = _make_camera(perspective_flags=0)
        with pytest.raises(StrictMirrorError, match="camera_unknown_projection"):
            describe_camera(cam, 0, options={"strict_mirror": True})

    def test_missing_eye_strict_raises(self):
        cam = _make_camera(position=None)
        with pytest.raises(StrictMirrorError, match="camera_missing_eye_or_target"):
            describe_camera(cam, 0, options={"strict_mirror": True})

    def test_missing_target_strict_raises(self):
        cam = _make_camera(interest=None)
        with pytest.raises(StrictMirrorError, match="camera_missing_eye_or_target"):
            describe_camera(cam, 0, options={"strict_mirror": True})

    def test_degenerate_near_far_strict_warns_but_does_not_raise(self):
        # Degenerate near/far is non-fatal: game renders something, just wrong.
        cam = _make_camera(near=0.0, far=0.0)
        ir = describe_camera(cam, 0, options={"strict_mirror": True})
        assert ir is not None


# ---------------------------------------------------------------------------
# L7: Unknown keyframe opcode
# ---------------------------------------------------------------------------

class TestKeyframeOpcode:
    def _make_fobj(self, opcode_byte):
        """Build an FObj stream with a single opcode + float value + wait terminator."""
        from shared.helpers.binary import pack_native
        # byte 0: opcode in low 4 bits, node count = 1 (encoded as (count-1)<<4 = 0)
        raw = bytearray([opcode_byte & 0x0F])
        raw.extend(pack_native('float', 1.0))
        raw.append(0)  # wait=0 terminator
        from shared.Constants.hsd import HSD_A_FRAC_FLOAT
        return SimpleNamespace(
            type=0, raw_ad=bytes(raw), data_length=len(raw),
            start_frame=0.0, frac_value=HSD_A_FRAC_FLOAT, frac_slope=HSD_A_FRAC_FLOAT,
            next=None,
        )

    def test_known_opcode_lenient(self):
        from importer.phases.describe.helpers.keyframe_decoder import decode_fobjdesc
        from shared.Constants.hsd import HSD_A_OP_LIN
        fobj = self._make_fobj(HSD_A_OP_LIN)
        logger = StubLogger()
        kfs = decode_fobjdesc(fobj, logger=logger)
        assert len(kfs) == 1

    def test_unknown_opcode_lenient_falls_back(self):
        from importer.phases.describe.helpers.keyframe_decoder import decode_fobjdesc
        # Opcode 0x7 is not in _INTERPOLATION_MAP (valid set: 0-6)
        fobj = self._make_fobj(0x7)
        logger = StubLogger()
        kfs = decode_fobjdesc(fobj, logger=logger)  # no strict → lenient fallback
        assert len(kfs) == 1  # Falls back to CONSTANT

    def test_unknown_opcode_strict_raises(self):
        from importer.phases.describe.helpers.keyframe_decoder import decode_fobjdesc
        fobj = self._make_fobj(0x7)
        logger = StubLogger()
        with pytest.raises(StrictMirrorError, match="keyframe_unknown_opcode"):
            decode_fobjdesc(fobj, logger=logger, options={"strict_mirror": True})


# ---------------------------------------------------------------------------
# Missing vertex colors (game renders unlit; strict raises)
# ---------------------------------------------------------------------------

class TestMissingVertexColors:
    def _run_describe(self, strict):
        """Build a minimal DObject → PObject with no CLR0 vertex and run describe_meshes."""
        from importer.phases.describe.helpers.meshes import describe_meshes
        from shared.helpers.math_shim import Matrix
        from shared.Constants.gx import GX_VA_POS

        # Minimal position-only PObj
        vtx_pos = SimpleNamespace(attribute=GX_VA_POS, isTexture=lambda: False)
        vertex_list = SimpleNamespace(vertices=[vtx_pos])
        pobj = SimpleNamespace(
            address=0x1234,
            name='p',
            vertex_list=vertex_list,
            sources=[[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]],
            face_lists=[[[0, 1, 2]]],
            property=None,
            flags=0,
            next=None,
        )
        mesh = SimpleNamespace(
            address=0x100, pobject=pobj, mobject=None, next=None,
        )
        joint = SimpleNamespace(
            address=0x10, flags=0, name='Bone_0', property=mesh,
            child=None, next=None,
        )
        bone = SimpleNamespace(
            name='Bone_0', flags=0,
            world_matrix=[list(row) for row in Matrix.Identity(4)],
            inverse_bind_matrix=None, parent_index=None, mesh_indices=[],
            scale=(1, 1, 1), position=(0, 0, 0), rotation=(0, 0, 0),
            local_matrix=[list(row) for row in Matrix.Identity(4)],
            normalized_world_matrix=[list(row) for row in Matrix.Identity(4)],
            accumulated_scale=(1, 1, 1),
        )
        options = {"strict_mirror": True} if strict else {}
        return describe_meshes(joint, [bone], {0x10: 0}, logger=StubLogger(), options=options)

    def test_lenient_fabricates_white_colors(self):
        meshes = self._run_describe(strict=False)
        assert len(meshes) == 1
        # Lenient path: fabricated white color_0 and alpha_0 layers
        layer_names = {cl.name for cl in meshes[0].color_layers}
        assert 'color_0' in layer_names
        assert 'alpha_0' in layer_names

    def test_strict_skips_fabrication(self):
        # Strict path: colour layers left absent so the mesh renders unlit —
        # matching in-game behaviour. Import completes; no exception is raised.
        meshes = self._run_describe(strict=True)
        assert len(meshes) == 1
        layer_names = {cl.name for cl in meshes[0].color_layers}
        assert 'color_0' not in layer_names
        assert 'alpha_0' not in layer_names
