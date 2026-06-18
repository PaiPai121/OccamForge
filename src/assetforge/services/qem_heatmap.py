from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


SUPPORTED_QEM_HEATMAP_EXTENSIONS = {".blend", ".obj", ".fbx", ".glb", ".gltf"}


class QemHeatmapGenerator(ABC):
    """Port implemented by infrastructure that can compute diagnostic QEM edge costs."""

    @abstractmethod
    def generate_qem_heatmap(
        self,
        source_file: Path,
        output_directory: Path,
    ) -> dict[str, Any]:
        raise NotImplementedError


class QemHeatmapService:
    """Generates QEM edge cost diagnostics without modifying mesh topology."""

    def __init__(self, generator: QemHeatmapGenerator) -> None:
        self._generator = generator

    def generate(
        self,
        source_file: Path,
        output_directory: Path | None = None,
    ) -> dict[str, Any]:
        if not source_file.exists():
            raise FileNotFoundError(f"Model file does not exist: {source_file}")
        if source_file.suffix.lower() not in SUPPORTED_QEM_HEATMAP_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_QEM_HEATMAP_EXTENSIONS))
            raise ValueError(f"Expected one of {supported}, got: {source_file}")

        report_directory = output_directory or source_file.parent / "qem_heatmaps"
        return self._generator.generate_qem_heatmap(source_file, report_directory)
