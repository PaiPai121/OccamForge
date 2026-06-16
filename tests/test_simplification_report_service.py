from pathlib import Path

import pytest

from assetforge.domain.simplification_report import SimplificationReport
from assetforge.services.simplification_report import SimplificationReportService


class FakeSimplificationReporter:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path, Path]] = []

    def generate_simplification_report(
        self,
        source_blend_file: Path,
        optimized_blend_file: Path,
        output_directory: Path,
    ) -> SimplificationReport:
        self.calls.append((source_blend_file, optimized_blend_file, output_directory))
        return SimplificationReport(
            source_blend_file=source_blend_file,
            optimized_blend_file=optimized_blend_file,
            report_json_path=output_directory / "simplification_report.json",
            heatmap_image_path=output_directory / "simplification_heatmap.png",
            original_triangle_count=100,
            optimized_triangle_count=80,
            removed_triangle_count=20,
            reduction_percentage=20.0,
            regions=(),
        )


def test_simplification_report_service_uses_default_optimized_path(tmp_path: Path) -> None:
    source = tmp_path / "vehicle.blend"
    optimized = tmp_path / "vehicle_optimized.blend"
    output = tmp_path / "reports"
    source.write_bytes(b"source")
    optimized.write_bytes(b"optimized")
    reporter = FakeSimplificationReporter()

    report = SimplificationReportService(reporter).generate(source, output_directory=output)

    assert report.optimized_blend_file == optimized
    assert reporter.calls == [(source, optimized, output)]


def test_simplification_report_service_requires_optimized_file(tmp_path: Path) -> None:
    source = tmp_path / "vehicle.blend"
    source.write_bytes(b"source")

    with pytest.raises(FileNotFoundError, match="Run Optimize first"):
        SimplificationReportService(FakeSimplificationReporter()).generate(source)
