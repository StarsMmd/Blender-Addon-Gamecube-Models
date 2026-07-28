"""Tests for particle-spawn (type-PTCL) animation track decode/encode.

Covers the raw-int stream decoder, the describe-side REF resolution into
IRParticleEmitEvents, the compose-side Frame emission, and the full
binding round-trip on real models when available.
"""
import os
import pytest
from types import SimpleNamespace

from importer.phases.describe.helpers.keyframe_decoder import decode_particle_fobj
from importer.phases.describe.helpers.animations import _decode_bone_channels
from exporter.phases.compose.helpers.animations import (
    _encode_particle_channel, _build_animation,
)
from shared.Constants.hsd import HSD_A_J_PTCL, HSD_A_J_ROTX
from shared.IR.animation import IRBoneTrack, IRKeyframe
from shared.IR.particles import IRParticleEmitEvent
from shared.IR.enums import Interpolation


def _fobj(raw_ad, start_frame=0.0, frac_value=0x00, frac_slope=0x00):
    return SimpleNamespace(
        type=HSD_A_J_PTCL, raw_ad=raw_ad, start_frame=start_frame,
        frac_value=frac_value, frac_slope=frac_slope, next=None,
        data_length=len(raw_ad),
    )


def _packed(genid, flags=0):
    return ((genid << 6) | flags).to_bytes(4, 'little')


# ---------------------------------------------------------------------------
# Raw stream decoder
# ---------------------------------------------------------------------------

def test_decode_single_event():
    # KEY op, 1 node: value (genid 2, flags 3), wait 0
    ad = bytes([0x06]) + _packed(2, 3) + bytes([0x00])
    events = decode_particle_fobj(_fobj(ad))
    assert events == [(0, (2 << 6) | 3)]


def test_decode_multi_event_with_waits():
    # KEY op, 2 nodes: genid 0 at frame 0, wait 25, genid 1 at frame 25
    ad = bytes([0x16]) + _packed(0) + bytes([25]) + _packed(1) + bytes([0x00])
    events = decode_particle_fobj(_fobj(ad))
    assert events == [(0, 0 << 6), (25, 1 << 6)]


def test_decode_extended_wait():
    # wait 200 needs two bytes: (200 & 0x7F) | 0x80, then 200 >> 7
    ad = (bytes([0x16]) + _packed(0) + bytes([(200 & 0x7F) | 0x80, 200 >> 7])
          + _packed(3) + bytes([0x00]))
    events = decode_particle_fobj(_fobj(ad))
    assert events == [(0, 0), (200, 3 << 6)]


def test_decode_respects_start_frame():
    ad = bytes([0x06]) + _packed(1) + bytes([0x00])
    events = decode_particle_fobj(_fobj(ad, start_frame=-10.0))
    assert events == [(10, 1 << 6)]


def test_decode_empty_stream():
    assert decode_particle_fobj(_fobj(b'')) == []


# ---------------------------------------------------------------------------
# Describe-side resolution
# ---------------------------------------------------------------------------

def _channels_for(ad, ref_map):
    aobj = SimpleNamespace(frame=_fobj(ad))
    options = {'particle_ref_map': ref_map} if ref_map is not None else {}
    return _decode_bone_channels(aobj, options=options)


def test_emits_resolved_through_ref_map():
    ad = bytes([0x16]) + _packed(400) + bytes([10]) + _packed(402) + bytes([0x00])
    _, _, _, _, emits = _channels_for(ad, {400: 0, 401: 1, 402: 2})
    assert [(e.frame, e.emitter_ref) for e in emits] == [(0.0, 0), (10.0, 2)]


def test_flag_bits_masked_off():
    ad = bytes([0x06]) + _packed(5, flags=0x3F) + bytes([0x00])
    _, _, _, _, emits = _channels_for(ad, {5: 1})
    assert [(e.frame, e.emitter_ref) for e in emits] == [(0.0, 1)]


def test_unknown_generator_id_dropped():
    ad = bytes([0x06]) + _packed(999) + bytes([0x00])
    _, _, _, _, emits = _channels_for(ad, {0: 0})
    assert emits == []


def test_no_ref_map_drops_events():
    ad = bytes([0x06]) + _packed(1) + bytes([0x00])
    _, _, _, _, emits = _channels_for(ad, None)
    assert emits == []


# ---------------------------------------------------------------------------
# Compose-side emission
# ---------------------------------------------------------------------------

def test_encode_particle_channel_round_trip():
    events = [
        IRParticleEmitEvent(frame=0.0, emitter_ref=2),
        IRParticleEmitEvent(frame=30.0, emitter_ref=0),
        IRParticleEmitEvent(frame=300.0, emitter_ref=5),
    ]
    frame = _encode_particle_channel(events)
    assert frame.type == HSD_A_J_PTCL
    assert frame.frac_value == 0x00

    decoded = decode_particle_fobj(frame)
    assert [(f, v >> 6) for f, v in decoded] == [(0, 2), (30, 0), (300, 5)]
    # flag bits are written as zero (dead at runtime)
    assert all((v & 0x3F) == 0 for _, v in decoded)


def test_encode_orders_events_by_frame():
    events = [
        IRParticleEmitEvent(frame=50.0, emitter_ref=1),
        IRParticleEmitEvent(frame=0.0, emitter_ref=0),
    ]
    decoded = decode_particle_fobj(_encode_particle_channel(events))
    assert [(f, v >> 6) for f, v in decoded] == [(0, 0), (50, 1)]


def _track(particle_emits, rotation=None):
    return IRBoneTrack(
        bone_name='b', bone_index=0,
        rotation=rotation or [[], [], []],
        location=[[], [], []],
        scale=[[], [], []],
        end_frame=60.0,
        particle_emits=particle_emits,
    )


def test_particle_frame_appended_last_in_chain():
    rot_x = [IRKeyframe(frame=0, value=0.5, interpolation=Interpolation.LINEAR),
             IRKeyframe(frame=10, value=1.0, interpolation=Interpolation.LINEAR)]
    track = _track([IRParticleEmitEvent(frame=0.0, emitter_ref=0)],
                   rotation=[rot_x, [], []])
    anim = _build_animation(track, loop=False)
    types = []
    frame = anim.frame
    while frame:
        types.append(frame.type)
        frame = frame.next
    assert types == [HSD_A_J_ROTX, HSD_A_J_PTCL]


def test_track_with_only_particle_emits_builds_chain():
    track = _track([IRParticleEmitEvent(frame=0.0, emitter_ref=3)])
    anim = _build_animation(track, loop=False)
    assert anim.frame is not None
    assert anim.frame.type == HSD_A_J_PTCL
    assert anim.frame.next is None


# ---------------------------------------------------------------------------
# Real-model integration
# ---------------------------------------------------------------------------

def test_real_model_binding_round_trip():
    """fire's spawn tracks decode to known events and survive re-encoding."""
    models_dir = '/Users/stars/Documents/Projects/DAT plugin/models'
    path = os.path.join(models_dir, 'fire.pkx')
    if not os.path.exists(path):
        pytest.skip('Real models not available')

    from shared.helpers.pkx import PKXContainer
    from shared.helpers.logger import StubLogger
    from importer.phases.route.route import route_sections
    from importer.phases.parse.parse import parse_sections
    from importer.phases.describe.describe import describe_scene
    from importer.phases.describe.helpers.particles import particle_ref_map

    container = PKXContainer.from_file(path)
    logger = StubLogger()
    sections = parse_sections(
        container.dat_bytes,
        route_sections(container.dat_bytes, logger=logger), {}, logger=logger)
    options = {'particle_ref_map': particle_ref_map(container.gpt1_data)}
    scene = describe_scene(sections, options, logger=logger)

    emitting_bones = set()
    total_events = 0
    identity = {i: i for i in range(len(options['particle_ref_map']))}
    for anim_set in scene.models[0].bone_animations:
        for track in anim_set.tracks:
            if not track.particle_emits:
                continue
            emitting_bones.add(track.bone_index)
            total_events += len(track.particle_emits)

            # Re-encode and re-decode: events must survive unchanged.
            frame = _encode_particle_channel(track.particle_emits)
            aobj = SimpleNamespace(frame=frame)
            _, _, _, _, emits2 = _decode_bone_channels(
                aobj, options={'particle_ref_map': identity})
            got = [(e.frame, e.emitter_ref) for e in emits2]
            want = [(e.frame, e.emitter_ref)
                    for e in sorted(track.particle_emits, key=lambda e: e.frame)]
            assert got == want

    assert total_events == 42
    assert emitting_bones == {66, 72, 80}
