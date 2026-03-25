"""Errors raised during Phase 5A — Blender Build."""


class ModelBuildError(Exception):
    """Failed to build Blender objects from IR scene."""
    def __init__(self, model_name, cause):
        self.model_name = model_name
        self.cause = cause

    def __str__(self):
        return "Failed to build model '%s': %s" % (self.model_name, self.cause)


class AnimationBakeError(Exception):
    """Failed to bake animation for a bone (e.g. singular matrix)."""
    def __init__(self, bone_name, frame, cause):
        self.bone_name = bone_name
        self.frame = frame
        self.cause = cause

    def __str__(self):
        return ("Animation bake failed for bone '%s' at frame %d: %s"
                % (self.bone_name, self.frame, self.cause))
