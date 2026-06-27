from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable


SUPPORTED_COLLAPSE_IMPACT_EXTENSIONS = {".blend", ".obj", ".fbx", ".glb", ".gltf"}


class CollapseImpactGenerator(ABC):
    """Port implemented by infrastructure that can simulate per-edge collapse impact."""

    @abstractmethod
    def generate_collapse_impact(
        self,
        source_file: Path,
        output_directory: Path,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class CollapseImpactService:
    """Generates a diagnostic heatmap for local after-collapse deformation."""

    def __init__(self, generator: CollapseImpactGenerator) -> None:
        self._generator = generator

    def generate(
        self,
        source_file: Path,
        output_directory: Path | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        if not source_file.exists():
            raise FileNotFoundError(f"Model file does not exist: {source_file}")
        if source_file.suffix.lower() not in SUPPORTED_COLLAPSE_IMPACT_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_COLLAPSE_IMPACT_EXTENSIONS))
            raise ValueError(f"Expected one of {supported}, got: {source_file}")

        report_directory = output_directory or source_file.parent / "collapse_impact"
        if progress_callback is None:
            return self._generator.generate_collapse_impact(source_file, report_directory)
        return self._generator.generate_collapse_impact(
            source_file,
            report_directory,
            progress_callback,
        )
