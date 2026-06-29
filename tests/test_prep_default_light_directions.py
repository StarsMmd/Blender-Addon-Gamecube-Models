"""The prep script's default directional lights face the right way.

Regression guard for the "default lights angle downwards" bug. The prep
script (`scripts/prepare_for_pkx_export.py::prepare_lights`) used to orient
its three SUN lamps with hand-picked Euler angles that all pointed
*downward* — negative GX-Y — whereas real Colo/XD models light the
dominant Main/Fill from *above* (positive GX-Y).

These tests read the actual `_DIRECTIONAL_LIGHTS` constant out of the
script via `ast` (the script auto-runs on import, so we parse it instead
of importing it) and check two things, both bpy-free:

  1. Main and Fill point from above (GX-Y > 0).
  2. The exporter's `plan_lights` collapse recovers each listed GX
     direction from the Blender forward vector the script builds — i.e.
     the GX→Blender map the script uses is the exact inverse of the
     exporter's Blender→GX map, so a prep light round-trips to its spec.
"""
import ast
import os

from shared.BR.lights import BRLight
from exporter.phases.plan.helpers.lights import plan_lights

_SCRIPT = os.path.join(
    os.path.dirname(__file__), '..', 'scripts', 'prepare_for_pkx_export.py',
)


def _directional_lights():
    """Extract the `_DIRECTIONAL_LIGHTS` literal from the prep script."""
    tree = ast.parse(open(_SCRIPT).read())
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == 'prepare_lights':
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign):
                    for t in node.targets:
                        if isinstance(t, ast.Name) and t.id == '_DIRECTIONAL_LIGHTS':
                            return ast.literal_eval(node.value)
    raise AssertionError("_DIRECTIONAL_LIGHTS not found in prepare_lights")


def test_main_and_fill_come_from_above():
    lights = {suffix: gx for suffix, _color, gx in _directional_lights()}
    # GX-Y is up. The bug was negative Y (lit from below) on every light.
    assert lights['Main'][1] > 0, "Main light should come from above"
    assert lights['Fill'][1] > 0, "Fill light should come from above"


def test_prep_directions_round_trip_through_plan_lights():
    for suffix, _color, gx in _directional_lights():
        gx_x, gx_y, gx_z = gx
        # The script orients the lamp so its -Z (the SUN forward the
        # exporter reads) is this Blender vector:
        forward = (gx_x, -gx_z, gx_y)
        br = BRLight(
            name='DATPlugin_Prep_' + suffix,
            blender_type='SUN',
            color=(1.0, 1.0, 1.0),
            energy=1.0,
            location=(0.0, 0.0, 0.0),
            target_location=forward,
        )
        ir = plan_lights([br])
        assert len(ir) == 1
        for got, want in zip(ir[0].position, gx):
            assert abs(got - want) < 1e-6, f"{suffix}: {ir[0].position} != {gx}"
