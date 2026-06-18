from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


SUPPORTED_SCALE_ANALYSIS_EXTENSIONS = {".blend", ".obj", ".fbx", ".glb", ".gltf"}


class ScaleAnalysisGenerator(ABC):
    """Port implemented by infrastructure that can run Scale Analysis V0."""

    @abstractmethod
    def generate_scale_analysis(
        self,
        source_file: Path,
        output_directory: Path,
    ) -> dict[str, Any]:
        raise NotImplementedError


class ScaleAnalysisService:
    """Generates scale persistence diagnostics without modifying mesh topology."""

    def __init__(self, generator: ScaleAnalysisGenerator) -> None:
        self._generator = generator

    def generate(
        self,
        source_file: Path,
        output_directory: Path | None = None,
    ) -> dict[str, Any]:
        if not source_file.exists():
            raise FileNotFoundError(f"Model file does not exist: {source_file}")
        if source_file.suffix.lower() not in SUPPORTED_SCALE_ANALYSIS_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_SCALE_ANALYSIS_EXTENSIONS))
            raise ValueError(f"Expected one of {supported}, got: {source_file}")

        report_directory = output_directory or source_file.parent / "scale_analysis"
        return self._generator.generate_scale_analysis(source_file, report_directory)
