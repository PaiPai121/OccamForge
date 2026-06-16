from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from assetforge.domain.simplification_report import SimplificationReport


class SimplificationReporter(ABC):
    """Port implemented by infrastructure that can compare original and optimized meshes."""

    @abstractmethod
    def generate_simplification_report(
        self,
        source_blend_file: Path,
        optimized_blend_file: Path,
        output_directory: Path,
    ) -> SimplificationReport:
        raise NotImplementedError


class SimplificationReportService:
    """Generates a diagnostic report showing where triangles were removed."""

    def __init__(self, reporter: SimplificationReporter) -> None:
        self._reporter = reporter

    def generate(
        self,
        source_blend_file: Path,
        optimized_blend_file: Path | None = None,
        output_directory: Path | None = None,
    ) -> SimplificationReport:
        if not source_blend_file.exists():
            raise FileNotFoundError(f"Blend file does not exist: {source_blend_file}")
        if source_blend_file.suffix.lower() != ".blend":
            raise ValueError(f"Expected a .blend file, got: {source_blend_file}")

        optimized = optimized_blend_file or source_blend_file.with_name(
            f"{source_blend_file.stem}_optimized{source_blend_file.suffix}"
        )
        if not optimized.exists():
            raise FileNotFoundError(
                "Optimized blend file does not exist. Run Optimize first or provide an optimized blend."
            )
        if optimized.suffix.lower() != ".blend":
            raise ValueError(f"Expected an optimized .blend file, got: {optimized}")

        report_directory = output_directory or source_blend_file.parent / "simplification_reports"
        return self._reporter.generate_simplification_report(
            source_blend_file,
            optimized,
            report_directory,
        )
