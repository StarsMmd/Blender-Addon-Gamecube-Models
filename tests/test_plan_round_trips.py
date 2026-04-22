"""Stubs for round-trip tests involving the Plan phase (IR → BR).

Both round-trip flows are deferred until the exporter has the symmetric
phase counterparts (inspect_blender: Blender → BR, un_plan: BR → IR).
For now these tests are skipped placeholders that document the intended
coverage and will become the real tests once the exporter side lands.

Until then, the Plan phase is validated only by unit tests on its
individual conversion helpers (IR→BR for armature, meshes, materials,
actions, etc. as each stage lands).

Flow reference:
    Import:  IR → plan → BR → build → Blender
    Export:  Blender → inspect → BR → un_plan → IR
"""
import pytest


@pytest.mark.skip(reason="Awaiting exporter inspect_blender + un_plan phases")
class TestIBIRoundTripThroughPlan:
    """IR → Plan → Build → Blender → Inspect → UnPlan → IR.

    Extends the existing IBI round-trip test type to pass through the Plan
    phase on both sides. Asserts that the IR re-derived after a full pass
    through Blender matches the original IR (field-level), bounding both
    directions of the BR conversion and the build/inspect steps.
    """

    def test_armature_survives_round_trip(self):
        pass

    def test_meshes_survive_round_trip(self):
        pass

    def test_materials_survive_round_trip(self):
        pass

    def test_actions_survive_round_trip(self):
        pass

    def test_constraints_survive_round_trip(self):
        pass


@pytest.mark.skip(reason="Awaiting exporter inspect_blender phase")
class TestBBBRoundTripThroughBuild:
    """BR → Build → Blender → Inspect → BR.

    New round-trip type introduced with the Plan phase: bounds just the
    Blender-facing build + inspect steps, independent of IR↔BR conversion.
    Assumes a BR as input (hand-crafted or produced by Plan from a fixture
    IR) and asserts the BR read back from Blender after build matches.

    Unit tests for individual Plan-phase helpers cover IR → BR directly;
    this class covers the round-trip through bpy.
    """

    def test_armature_round_trip(self):
        pass

    def test_mesh_round_trip(self):
        pass

    def test_material_round_trip(self):
        pass

    def test_action_round_trip(self):
        pass
