"""Light animation round-trip: describe_light_animations → compose.

Map archives attach a LightAnimation node to each LightSet. Even when the
node is empty (all child pointers null — common in the corpus), its
presence is scene structure and must survive describe → compose so the
NIN round-trip doesn't count it as a miss.
"""
from types import SimpleNamespace

from importer.phases.describe.helpers.lights import describe_light_animations
from exporter.phases.compose.helpers.lights import _compose_light_animations
from shared.IR.lights import IRLightKeyframes
from shared.helpers.scale import GC_TO_METERS as S
from shared.helpers.binary import pack_native
from shared.Constants.hsd import (
    HSD_A_L_VIS, HSD_A_W_TRAX,
    HSD_A_OP_LIN, HSD_A_FRAC_FLOAT,
)


def _make_frame(fobj_type, values):
    """Build a mock Frame node with raw_ad encoding LIN keyframes at integer
    frames — same encoding the describe camera-animation tests use."""
    raw = bytearray()
    count = len(values)
    first_3 = (count - 1) & 7
    remaining = (count - 1) >> 3
    first_byte = HSD_A_OP_LIN | (first_3 << 4)
    if remaining > 0:
        first_byte |= 0x80
    raw.append(first_byte)
    while remaining > 0:
        ext = remaining & 0x7F
        remaining >>= 7
        if remaining > 0:
            ext |= 0x80
        raw.append(ext)
    for i, v in enumerate(values):
        raw.extend(pack_native('float', v))
        raw.append(1 if i < count - 1 else 0)
    return SimpleNamespace(
        type=fobj_type,
        frac_value=HSD_A_FRAC_FLOAT,
        frac_slope=HSD_A_FRAC_FLOAT,
        start_frame=0.0,
        raw_ad=bytes(raw),
        data_length=len(raw),
        next=None,
    )


def _make_aobj(end_frame=10.0, flags=0, frame=None):
    return SimpleNamespace(end_frame=end_frame, flags=flags, frame=frame)


def _make_wobject_animation(aobj=None):
    return SimpleNamespace(animation=aobj, render_animation=None)


def _make_light_animation(aobj=None, eye=None, interest=None, nxt=None):
    return SimpleNamespace(
        next=nxt,
        animation=aobj,
        eye_position_animation=eye,
        interest_animation=interest,
    )


def _make_light_set(animations=None):
    return SimpleNamespace(light=object(), animations=animations)


class TestDescribeLightAnimations:

    def test_no_animations_returns_empty(self):
        assert describe_light_animations(_make_light_set(None)) == []
        assert describe_light_animations(_make_light_set([])) == []

    def test_empty_node_still_emitted(self):
        # An all-null LightAnimation node is empty but present.
        ls = _make_light_set([_make_light_animation()])
        result = describe_light_animations(ls)
        assert len(result) == 1
        kf = result[0]
        assert kf.color_r is None and kf.eye_x is None and kf.cutoff is None

    def test_next_chain_flattened(self):
        # animations array holds the head; siblings hang off `.next`.
        tail = _make_light_animation()
        head = _make_light_animation(nxt=tail)
        ls = _make_light_set([head])
        assert len(describe_light_animations(ls)) == 2

    def test_visibility_track_decoded(self):
        vis = _make_frame(HSD_A_L_VIS, [1.0, 0.0])
        aobj = _make_aobj(end_frame=1.0, frame=vis)
        ls = _make_light_set([_make_light_animation(aobj=aobj)])
        result = describe_light_animations(ls)
        assert len(result) == 1
        assert result[0].visibility is not None
        assert len(result[0].visibility) == 2

    def test_eye_position_scaled_to_meters(self):
        eye_x = _make_frame(HSD_A_W_TRAX, [100.0])
        eye_anim = _make_wobject_animation(_make_aobj(frame=eye_x))
        ls = _make_light_set([_make_light_animation(eye=eye_anim)])
        result = describe_light_animations(ls)
        assert result[0].eye_x is not None
        assert abs(result[0].eye_x[0].value - 100.0 * S) < 1e-4


class TestComposeLightAnimations:

    def test_none_composes_none(self):
        assert _compose_light_animations(None, _Log()) is None
        assert _compose_light_animations([], _Log()) is None

    def test_empty_clip_composes_empty_node(self):
        clip = IRLightKeyframes(name="a")
        nodes = _compose_light_animations([clip], _Log())
        assert len(nodes) == 1
        n = nodes[0]
        assert n.animation is None
        assert n.eye_position_animation is None
        assert n.interest_animation is None
        assert n.next is None

    def test_count_preserved(self):
        clips = [IRLightKeyframes(name="a"), IRLightKeyframes(name="b")]
        nodes = _compose_light_animations(clips, _Log())
        assert len(nodes) == 2


class TestLightAnimationBRRoundTrip:
    """IR → BR → IR (the IBI plan legs) must carry light animation clips."""

    def _light(self, animations):
        from shared.IR.lights import IRLight
        from shared.IR.enums import LightType
        return IRLight(name="L", type=LightType.POINT, color=(1, 1, 1),
                       position=(0, 0, 0), animations=animations)

    def test_empty_presence_clip_round_trips(self):
        from importer.phases.plan.helpers.scene import plan_light
        from exporter.phases.plan.helpers.lights import plan_lights
        from shared.BR.lights import BRLightAnimation

        ir_light = self._light([IRLightKeyframes(name="clip0")])
        br = plan_light(ir_light)
        assert len(br.animations) == 1
        assert isinstance(br.animations[0], BRLightAnimation)
        rec = plan_lights([br])[0]
        assert len(rec.animations) == 1
        # All channels stay None (track-less presence clip).
        kf = rec.animations[0]
        assert all(getattr(kf, f) is None for f in
                   ('color_r', 'visibility', 'cutoff', 'eye_x', 'target_z'))

    def test_position_channel_coord_flip_round_trips(self):
        from importer.phases.plan.helpers.scene import plan_light
        from exporter.phases.plan.helpers.lights import plan_lights
        from shared.IR.animation import IRKeyframe
        from shared.IR.enums import Interpolation

        kf = IRKeyframe(frame=0.0, value=7.0, interpolation=Interpolation.LINEAR)
        clip = IRLightKeyframes(name="c", eye_z=[kf])  # eye_z → loc_y (negated)
        rec = plan_lights([plan_light(self._light([clip]))])[0]
        # eye_z survives the flip → -(-7) = 7
        assert rec.animations[0].eye_z[0].value == 7.0


class _Log:
    def debug(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass
