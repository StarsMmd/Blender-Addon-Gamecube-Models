"""Errors raised during Phase 5A — Blender Build."""


class ModelBuildError(Exception):
    """Failed to build Blender objects from the BR scene."""
    def __init__(self, model_name, cause):
        """Capture which model failed + the wrapped cause exception.

        In: model_name (str, model filename or identifier); cause (Exception).
        Out: None; instance attributes ``model_name`` and ``cause`` are set.
        """
        self.model_name = model_name
        self.cause = cause

    def __str__(self):
        """Human-readable message combining model name and underlying cause.

        In: (self).
        Out: str.
        """
        return "Failed to build model '%s': %s" % (self.model_name, self.cause)
