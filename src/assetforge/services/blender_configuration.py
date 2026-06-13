from __future__ import annotations

from pathlib import Path

from assetforge.blender.locator import BlenderDiscoveryResult, BlenderLocator
from assetforge.core.config import UserConfigStore


class BlenderConfigurationService:
    """Application service for finding and saving the Blender executable."""

    def __init__(self, locator: BlenderLocator, config_store: UserConfigStore) -> None:
        self._locator = locator
        self._config_store = config_store

    def auto_discover(self) -> BlenderDiscoveryResult | None:
        return self._locator.locate()

    def save_manual_path(self, executable: Path) -> BlenderDiscoveryResult:
        if not self._locator.is_valid_blender(executable):
            raise ValueError("Selected file is not a valid Blender executable.")
        resolved = executable.resolve()
        self._config_store.save_blender_path(resolved)
        return BlenderDiscoveryResult(executable=resolved, source="manual browse")

    def saved_path(self) -> Path | None:
        return self._config_store.saved_blender_path()
