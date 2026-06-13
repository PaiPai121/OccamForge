from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from assetforge.blender.exceptions import BlenderExecutionError, BlenderNotConfiguredError
from assetforge.blender.locator import BlenderLocator
from assetforge.core.config import AssetForgeConfig

LOGGER = logging.getLogger(__name__)


class BlenderBackgroundExecutor:
    """Runs Python scripts inside Blender background mode."""

    def __init__(self, config: AssetForgeConfig, locator: BlenderLocator) -> None:
        self._config = config
        self._locator = locator

    def run_script(self, script_path: Path, arguments: list[str]) -> dict[str, Any]:
        blender = self._resolve_blender_executable()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as output_file:
            output_path = Path(output_file.name)

        command = [
            str(blender),
            "--background",
            "--python",
            str(script_path),
            "--",
            *arguments,
            "--output-json",
            str(output_path),
        ]
        LOGGER.info("Running Blender command: %s", " ".join(command))

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._config.command_timeout_seconds,
                check=False,
            )
            if completed.returncode != 0:
                raise BlenderExecutionError(
                    "Blender command failed with exit code "
                    f"{completed.returncode}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
                )
            return json.loads(output_path.read_text(encoding="utf-8"))
        except subprocess.TimeoutExpired as exc:
            raise BlenderExecutionError("Blender command timed out.") from exc
        finally:
            output_path.unlink(missing_ok=True)

    def _resolve_blender_executable(self) -> Path:
        result = self._locator.locate()
        if result is not None:
            return result.executable

        raise BlenderNotConfiguredError(
            "Blender executable was not found. Use Settings > Browse Blender or set "
            "ASSETFORGE_BLENDER_PATH to blender.exe."
        )
