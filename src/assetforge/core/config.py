from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def default_user_config_path() -> Path:
    base_dir = os.getenv("APPDATA")
    if base_dir:
        return Path(base_dir) / "AssetForge" / "config.json"
    return Path.home() / ".assetforge" / "config.json"


@dataclass(frozen=True, slots=True)
class AssetForgeConfig:
    blender_executable: Path | None = None
    log_level: str = "INFO"
    command_timeout_seconds: int = 300
    user_config_path: Path = default_user_config_path()

    @classmethod
    def from_environment(cls) -> "AssetForgeConfig":
        blender_path = os.getenv("ASSETFORGE_BLENDER_PATH")
        timeout = os.getenv("ASSETFORGE_COMMAND_TIMEOUT_SECONDS")
        return cls(
            blender_executable=Path(blender_path) if blender_path else None,
            log_level=os.getenv("ASSETFORGE_LOG_LEVEL", "INFO"),
            command_timeout_seconds=int(timeout) if timeout else 300,
        )


class UserConfigStore:
    """Small JSON-backed store for user preferences."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or default_user_config_path()

    @property
    def config_path(self) -> Path:
        return self._config_path

    def load(self) -> dict[str, Any]:
        if not self._config_path.exists():
            return {}
        try:
            return json.loads(self._config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def saved_blender_path(self) -> Path | None:
        value = self.load().get("blender_executable")
        return Path(value) if value else None

    def save_blender_path(self, blender_executable: Path) -> None:
        payload = self.load()
        payload["blender_executable"] = str(blender_executable)
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
