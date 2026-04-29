"""Stubs for round-trip tests involving the Plan phase (IR ↔ BR).

These tests need a real Blender (bpy) runtime — the build / describe
steps drive bpy operators — so they remain skipped under the headless
pytest suite. The round-trip runner under tests/round_trip/ exercises
the same flow against real model files when invoked via python3.11.

Flow reference:
    Import:  IR → plan (importer) → BR → build → Blender
    Export:  Blender → describe (exporter) → BR → plan (exporter) → IR
"""
import pytest


@pytest.mark.skip(reason="Requires real bpy — exercised via tests/round_trip/")
class TestIBIRoundTripThroughPlan:
    """IR → plan → BR → build → Blender → describe → BR → plan → IR.

    Extends the existing IBI round-trip test type to pass through the Plan
    phase on both sides. Asserts that the IR re-derived after a full pass
    through Blender matches the original IR (field-level), bounding both
    directions of the BR conversion and the build/describe steps.
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


@pytest.mark.skip(reason="Requires real bpy — exercised via tests/round_trip/")
class TestBBBRoundTripThroughBuild:
    """BR → build → Blender → describe → BR.

    New round-trip type introduced with the Plan phase: bounds just the
    Blender-facing build + describe steps, independent of IR↔BR conversion.
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
