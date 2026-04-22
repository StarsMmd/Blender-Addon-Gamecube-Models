"""Errors raised during Phase 5A — Blender Build."""


class ModelBuildError(Exception):
    """Failed to build Blender objects from the BR scene."""
    def __init__(self, model_name, cause):
        self.model_name = model_name
        self.cause = cause

    def __str__(self):
        return "Failed to build model '%s': %s" % (self.model_name, self.cause)
