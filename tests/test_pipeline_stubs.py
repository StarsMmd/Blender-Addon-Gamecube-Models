"""Tests for pipeline phase stubs."""
from shared.IR import IRScene
from importer.phases.describe.describe import describe_scene
from importer.phases.build_blender.build_blender import build_blender_scene


def test_describe_scene_returns_ir_scene():
    """describe_scene() should return an IRScene even with empty input."""
    result = describe_scene(sections=[], options={})
    assert isinstance(result, IRScene)
    assert result.models == []
    assert result.lights == []


def test_build_blender_scene_accepts_ir_scene():
    """build_blender_scene() should accept an IRScene without error."""
    scene = IRScene()
    # Should not raise
    build_blender_scene(scene, context=None, options={})
