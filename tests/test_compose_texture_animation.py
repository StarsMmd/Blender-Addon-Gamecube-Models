"""Regression: TextureAnimation nodes built by compose must expose every
field declared on the class, so serialize can call getattr() without a crash.

Previously only image_table_count / palette_table_count were assigned, while
the matching image_table / palette_table pointer fields were left off the
instance. Node.writePrivateData iterates `cls.fields` with a bare getattr,
which raised AttributeError mid-serialize and aborted the whole PKX export
silently past the "Export Phase 3: Serialize" boundary.
"""
from types import SimpleNamespace

from shared.IR.animation import IRKeyframe, IRTextureUVTrack
from shared.IR.enums import Interpolation
from shared.Nodes.Classes.Texture.TextureAnimation import TextureAnimation
from exporter.phases.compose.helpers.material_animations import (
    _build_texture_animation, _unflip_translation_v,
)


def _kf(frame, value):
    return IRKeyframe(
        frame=float(frame), value=float(value),
        interpolation=Interpolation.LINEAR,
        handle_left=(frame - 1.0, value),
        handle_right=(frame + 1.0, value),
    )


def test_build_texture_animation_sets_every_declared_field():
    uv = IRTextureUVTrack(texture_index=3)
    uv.translation_u = [_kf(0, 0.0), _kf(10, 0.5)]

    ta = _build_texture_animation(uv, None, loop=False)
    assert ta is not None

    # All fields declared on TextureAnimation.fields must be set as
    # attributes — Node.writePrivateData uses getattr() directly.
    for field_name, _ in TextureAnimation.fields:
        assert hasattr(ta, field_name), (
            f"TextureAnimation missing attribute {field_name!r} — "
            f"will AttributeError during serialize")


def test_build_texture_animation_image_and_palette_tables_are_empty():
    # With no baked image frames, the table pointers should be None
    # (writePrivateData converts None → 0, i.e. null pointer).
    uv = IRTextureUVTrack(texture_index=0)
    uv.scale_u = [_kf(0, 1.0), _kf(5, 2.0)]

    ta = _build_texture_animation(uv, None, loop=True)
    assert ta.image_table is None
    assert ta.palette_table is None
    assert ta.image_table_count == 0
    assert ta.palette_table_count == 0


def test_unflip_translation_v_uses_static_scale_from_texture_layer():
    # Regression: eye blink animations use multi-frame stacked textures
    # (e.g. scale_v=0.25 for 4 vertically stacked blink frames). The
    # importer V-flips translation_v with v_ir = 1 - static_scale_v - v_gx
    # using the TObj's actual scale[1]. The exporter previously reversed
    # this with scale_v=1.0 hard-coded, producing off-by-(1-scale) values
    # that pushed the eye UV outside the visible region.
    #
    # Forward: v_ir = 1 - 0.25 - v_gx    -> for v_gx=0.0, v_ir = 0.75
    # Reverse: v_gx = 1 - 0.25 - v_ir    -> for v_ir=0.75, v_gx = 0.0 ✓
    kfs_in = [_kf(0, 0.75), _kf(10, 0.25)]  # IR-space values (V-flipped)
    out = _unflip_translation_v(kfs_in, scale_kfs=None, static_scale_v=0.25)
    assert out[0].value == 0.0
    assert out[1].value == 0.5


def test_build_texture_animation_forwards_static_scale_from_layer(monkeypatch):
    # End-to-end: _build_texture_animation reads the texture_layer's
    # scale[1] and pipes it into the V-flip reversal. Spy on
    # _unflip_translation_v to confirm the scale arrives at the helper.
    import exporter.phases.compose.helpers.material_animations as mod

    uv = IRTextureUVTrack(texture_index=0)
    uv.translation_v = [_kf(0, 0.75), _kf(10, 0.25)]
    layer = SimpleNamespace(scale=(1.0, 0.25, 1.0))

    captured = {}
    real = mod._unflip_translation_v

    def spy(translation_kfs, scale_kfs, static_scale_v=1.0):
        captured['static_scale_v'] = static_scale_v
        return real(translation_kfs, scale_kfs, static_scale_v)

    monkeypatch.setattr(mod, '_unflip_translation_v', spy)

    mod._build_texture_animation(uv, layer, loop=False)
    assert captured['static_scale_v'] == 0.25


def test_build_texture_animation_defaults_static_scale_without_layer():
    # When the IRMaterial lookup fails (layer=None), fall back to scale_v=1.0.
    # This matches the pre-fix behaviour for single-texture materials where
    # the TObj's static scale is always 1.0.
    uv = IRTextureUVTrack(texture_index=0)
    uv.translation_v = [_kf(0, 0.25), _kf(10, 0.75)]

    out = _unflip_translation_v(uv.translation_v, None, static_scale_v=1.0)
    # 1 - 1 - 0.25 = -0.25;  1 - 1 - 0.75 = -0.75
    assert abs(out[0].value - (-0.25)) < 1e-6
    assert abs(out[1].value - (-0.75)) < 1e-6
