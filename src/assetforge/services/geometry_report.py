from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from assetforge.domain.geometry_report import GeometryReport


SUPPORTED_GEOMETRY_EXTENSIONS = {".blend", ".obj", ".fbx", ".glb", ".gltf"}


class GeometryReporter(ABC):
    """Port implemented by infrastructure that can analyze raw model geometry."""

    @abstractmethod
    def generate_geometry_report(
        self,
        source_file: Path,
        output_directory: Path,
    ) -> GeometryReport:
        raise NotImplementedError


class GeometryReportService:
    """Generates a geometry distribution report without optimizing or exporting."""

    def __init__(self, reporter: GeometryReporter) -> None:
        self._reporter = reporter

    def generate(
        self,
        source_file: Path,
        output_directory: Path | None = None,
    ) -> GeometryReport:
        if not source_file.exists():
            raise FileNotFoundError(f"Model file does not exist: {source_file}")
        if source_file.suffix.lower() not in SUPPORTED_GEOMETRY_EXTENSIONS:
            supported = ", ".join(sorted(SUPPORTED_GEOMETRY_EXTENSIONS))
            raise ValueError(f"Expected one of {supported}, got: {source_file}")

        report_directory = output_directory or source_file.parent / "geometry_reports"
        return self._reporter.generate_geometry_report(source_file, report_directory)
