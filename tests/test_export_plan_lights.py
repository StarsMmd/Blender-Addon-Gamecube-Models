"""Tests for exporter/phases/plan/helpers/lights.py — BRLight → IRLight.

Focused on the SUN-direction collapse: the GX-native encoding of an
infinite light stores the direction unit-vector directly in `position`
with `interest=None`. The importer mirrors that on the Blender side by
moving the direction to `target_location` (so the Sun lamp gets a
TRACK_TO empty for round-trippable orientation), and this exporter
helper has to collapse that representation back to the native form so
the recomposed Light node reproduces the original bytes.
"""
from shared.BR.lights import BRLight
from shared.IR.enums import LightType
from exporter.phases.plan.helpers.lights import plan_lights


def test_sun_with_target_and_no_location_collapses_to_position():
    br = BRLight(
        name='Sun',
        blender_type='SUN',
        color=(1.0, 1.0, 1.0),
        energy=16.0,
        location=None,
        target_location=(1.0, -3.0, 2.0),  # Blender Z-up
    )
    ir = plan_lights([br])
    assert len(ir) == 1
    assert ir[0].type == LightType.SUN
    # Blender (x, y, z) → GC (x, z, -y): (1, -3, 2) → (1, 2, 3).
    assert ir[0].position == (1.0, 2.0, 3.0)
    assert ir[0].target_position is None


def test_sun_with_explicit_location_and_target_preserves_both():
    br = BRLight(
        name='Sun',
        blender_type='SUN',
        color=(1.0, 1.0, 1.0),
        energy=16.0,
        location=(0.5, -0.5, 0.5),
        target_location=(1.0, -1.0, 1.0),
    )
    ir = plan_lights([br])
    # Non-(0,0,0) location indicates the source authored an explicit
    # eye/interest pair — don't second-guess it.
    assert ir[0].position == (0.5, 0.5, 0.5)
    assert ir[0].target_position == (1.0, 1.0, 1.0)


def test_sun_with_origin_location_and_target_still_collapses():
    """When the importer hits the `obj.matrix_world ... forward = -Z`
    fallback in describe, it stamps location=(0,0,0) and puts the
    direction in target_location. Treat (0,0,0) as "no real position"
    so the collapse still happens."""
    br = BRLight(
        name='Sun',
        blender_type='SUN',
        color=(1.0, 1.0, 1.0),
        energy=16.0,
        location=(0.0, 0.0, 0.0),
        target_location=(1.0, -3.0, 2.0),
    )
    ir = plan_lights([br])
    assert ir[0].position == (1.0, 2.0, 3.0)
    assert ir[0].target_position is None


def test_point_light_does_not_collapse():
    """Only SUN gets the collapse — POINT lights have a real eye position."""
    br = BRLight(
        name='Point',
        blender_type='POINT',
        color=(1.0, 1.0, 1.0),
        energy=5.0,
        location=(0.0, 0.0, 0.0),
        target_location=(1.0, -3.0, 2.0),
    )
    ir = plan_lights([br])
    assert ir[0].type == LightType.POINT
    assert ir[0].position == (0.0, 0.0, 0.0)
    assert ir[0].target_position == (1.0, 2.0, 3.0)
