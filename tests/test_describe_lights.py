"""Tests for phases/describe/helpers/lights.py — light description."""
from types import SimpleNamespace

from importer.phases.describe.helpers.lights import describe_light
from shared.IR.lights import IRLight
from shared.helpers.scale import GC_TO_METERS as S
from shared.IR.enums import LightType
from shared.Constants.hsd import (
    LOBJ_AMBIENT, LOBJ_INFINITE, LOBJ_POINT, LOBJ_SPOT,
)


def _make_light(flags=0, name=None, color=None, position=None, interest=None):
    """Build a minimal Light-like object for testing."""
    return SimpleNamespace(
        flags=flags,
        name=name,
        color=color,
        position=position,
        interest=interest,
    )


def _make_color(red=0, green=0, blue=0, alpha=255):
    return SimpleNamespace(red=red, green=green, blue=blue, alpha=alpha)


def _make_wobject(position=(0, 0, 0)):
    return SimpleNamespace(position=position)


class TestDescribeLight:

    def test_sun_light(self):
        light = _make_light(flags=LOBJ_INFINITE, color=_make_color(255, 255, 255))
        ir = describe_light(light, light_index=0)
        assert isinstance(ir, IRLight)
        assert ir.type == LightType.SUN

    def test_point_light(self):
        light = _make_light(flags=LOBJ_POINT, color=_make_color(255, 128, 0))
        ir = describe_light(light, light_index=1)
        assert ir.type == LightType.POINT

    def test_spot_light(self):
        light = _make_light(flags=LOBJ_SPOT, color=_make_color(100, 200, 50))
        ir = describe_light(light, light_index=2)
        assert ir.type == LightType.SPOT

    def test_ambient_light(self):
        light = _make_light(flags=LOBJ_AMBIENT, color=_make_color(76, 76, 76))
        ir = describe_light(light)
        assert isinstance(ir, IRLight)
        assert ir.type == LightType.AMBIENT
        assert abs(ir.color[0] - 76 / 255) < 1e-5

    def test_brightness_from_property(self):
        light = _make_light(flags=LOBJ_INFINITE, color=_make_color(255, 255, 255))
        light.property = 16.0
        ir = describe_light(light)
        assert ir.brightness == 16.0

    def test_brightness_default(self):
        light = _make_light(flags=LOBJ_INFINITE, color=_make_color(255, 255, 255))
        ir = describe_light(light)
        assert ir.brightness == 1.0

    def test_color_is_srgb_normalized(self):
        """Light colors should be normalized [0-1] sRGB, not linearized."""
        light = _make_light(flags=LOBJ_POINT, color=_make_color(200, 100, 50))
        ir = describe_light(light)
        assert abs(ir.color[0] - 200 / 255) < 1e-5
        assert abs(ir.color[1] - 100 / 255) < 1e-5
        assert abs(ir.color[2] - 50 / 255) < 1e-5

    def test_color_black(self):
        light = _make_light(flags=LOBJ_POINT, color=_make_color(0, 0, 0))
        ir = describe_light(light)
        assert ir.color == (0.0, 0.0, 0.0)

    def test_color_white(self):
        light = _make_light(flags=LOBJ_POINT, color=_make_color(255, 255, 255))
        ir = describe_light(light)
        assert ir.color == (1.0, 1.0, 1.0)

    def test_default_color_when_none(self):
        light = _make_light(flags=LOBJ_POINT, color=None)
        ir = describe_light(light)
        assert ir.color == (1.0, 1.0, 1.0)

    def test_position_extracted(self):
        light = _make_light(
            flags=LOBJ_POINT,
            color=_make_color(255, 255, 255),
            position=_make_wobject(position=(1.0, 2.0, 3.0)),
        )
        ir = describe_light(light)
        assert ir.position == (1.0 * S, 2.0 * S, 3.0 * S)

    def test_no_position(self):
        light = _make_light(flags=LOBJ_POINT, color=_make_color(255, 255, 255))
        ir = describe_light(light)
        assert ir.position is None

    def test_target_position(self):
        light = _make_light(
            flags=LOBJ_SPOT,
            color=_make_color(255, 255, 255),
            interest=_make_wobject(position=(5.0, 6.0, 7.0)),
        )
        ir = describe_light(light)
        assert ir.target_position == (5.0 * S, 6.0 * S, 7.0 * S)

    def test_name_from_node(self):
        light = _make_light(flags=LOBJ_POINT, name='my_light',
                            color=_make_color(255, 255, 255))
        ir = describe_light(light, light_index=0)
        assert ir.name == 'Light_my_light'

    def test_ir_positions_are_yup_scaled(self):
        """IR stores Y-up positions with GC_TO_METERS scaling."""
        light = _make_light(
            flags=LOBJ_POINT,
            color=_make_color(255, 255, 255),
            position=_make_wobject(position=(10.0, 20.0, 30.0)),
            interest=_make_wobject(position=(5.0, 6.0, 7.0)),
        )
        ir = describe_light(light)
        # Y-up preserved, just scaled
        assert ir.position == (10.0 * S, 20.0 * S, 30.0 * S)
        assert ir.target_position == (5.0 * S, 6.0 * S, 7.0 * S)

    def test_name_from_index(self):
        light = _make_light(flags=LOBJ_POINT, name=None,
                            color=_make_color(255, 255, 255))
        ir = describe_light(light, light_index=3)
        assert ir.name == 'Light_3'
