from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from assetforge.blender.exceptions import BlenderExecutionError, BlenderNotConfiguredError
from assetforge.blender.locator import BlenderLocator
from assetforge.core.config import AssetForgeConfig

LOGGER = logging.getLogger(__name__)


class BlenderBackgroundExecutor:
    """Runs Python scripts inside Blender background mode."""

    def __init__(self, config: AssetForgeConfig, locator: BlenderLocator) -> None:
        self._config = config
        self._locator = locator

    def run_script(
        self,
        script_path: Path,
        arguments: list[str],
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
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
            if progress_callback is None:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self._config.command_timeout_seconds,
                    check=False,
                )
                stdout = completed.stdout
                stderr = completed.stderr
                returncode = completed.returncode
            else:
                returncode, stdout, stderr = self._run_script_streaming(command, progress_callback)
            if returncode != 0:
                raise BlenderExecutionError(
                    "Blender command failed with exit code "
                    f"{returncode}\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )
            output_text = output_path.read_text(encoding="utf-8")
            if not output_text.strip():
                raise BlenderExecutionError(
                    "Blender command did not produce a JSON report.\n"
                    f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )
            return json.loads(output_text)
        except subprocess.TimeoutExpired as exc:
            raise BlenderExecutionError("Blender command timed out.") from exc
        finally:
            output_path.unlink(missing_ok=True)

    def _run_script_streaming(
        self,
        command: list[str],
        progress_callback: Callable[[dict[str, Any]], None],
    ) -> tuple[int, str, str]:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        stdout_lines: list[str] = []
        if process.stdout is not None:
            for line in process.stdout:
                stdout_lines.append(line)
                if not line.startswith("ASSETFORGE_PROGRESS "):
                    continue
                try:
                    progress_callback(json.loads(line.removeprefix("ASSETFORGE_PROGRESS ").strip()))
                except json.JSONDecodeError:
                    LOGGER.debug("Ignored malformed progress line: %s", line.rstrip())
        try:
            process.wait(timeout=self._config.command_timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
        return process.returncode or 0, "".join(stdout_lines), ""

    def _resolve_blender_executable(self) -> Path:
        result = self._locator.locate()
        if result is not None:
            return result.executable

        raise BlenderNotConfiguredError(
            "Blender executable was not found. Use Settings > Browse Blender or set "
            "ASSETFORGE_BLENDER_PATH to blender.exe."
        )
