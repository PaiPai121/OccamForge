from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable


SUPPORTED_AFCOST_EXTENSIONS = {".blend", ".obj", ".fbx", ".glb", ".gltf"}


class AFCostCandidateGenerator(ABC):
    """Port implemented by infrastructure that can generate AF cost candidates."""

    @abstractmethod
    def generate_afcost_candidates(
        self,
        source_file: Path,
        output_directory: Path,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class AFCostCandidateService:
    """Generates research AF cost combinations without modifying mesh topology."""

    def __init__(self, generator: AFCostCandidateGenerator) -> None:
        self._generator = generator

    def generate(
        self,
        source_file: Path,
        output_directory: Path | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if not source_file.exists():
            raise FileNotFoundError(f"Model file does not exist: {source_file}")
        if source_file.suffix.lower() not in SUPPORTED_AFCOST_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_AFCOST_EXTENSIONS))
            raise ValueError(f"Expected one of {supported}, got: {source_file}")

        report_directory = output_directory or source_file.parent / "afcost_candidates"
        if progress_callback is None:
            return self._generator.generate_afcost_candidates(source_file, report_directory)
        return self._generator.generate_afcost_candidates(source_file, report_directory, progress_callback)
