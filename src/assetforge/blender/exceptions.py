from __future__ import annotations


class BlenderExecutionError(RuntimeError):
    """Raised when a Blender background command fails."""


class BlenderNotConfiguredError(BlenderExecutionError):
    """Raised when Blender executable cannot be resolved."""

