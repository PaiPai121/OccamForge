from pathlib import Path

import pytest

from assetforge.domain.geometry_report import (
    BoundingBox,
    BoundaryStats,
    GeometryOverallStats,
    GeometryReport,
    PlanarRegionStats,
    SilhouetteStats,
    TriangleDistribution,
)
from assetforge.services.geometry_report import GeometryReportService


class FakeGeometryReporter:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path]] = []

    def generate_geometry_report(self, source_file: Path, output_directory: Path) -> GeometryReport:
        self.calls.append((source_file, output_directory))
        return GeometryReport(
            source_file=source_file,
            report_json_path=output_directory / "geometry_report.json",
            heatmap_image_path=output_directory / "geometry_report.png",
            overall=GeometryOverallStats(
                vertices=1,
                edges=0,
                faces=0,
                triangles=0,
                bounding_box=BoundingBox(0, 0, 0, 0, 0, 0),
            ),
            planar_regions=PlanarRegionStats(0, 0.0, 0.0),
            curvature=(),
            boundary=BoundaryStats(0, 0.0),
            dense_regions=(),
            silhouette=SilhouetteStats(0, 0, 0, 0.0, 0, (), (), ()),
            triangle_distribution=TriangleDistribution(0.0, 0.0, 0.0),
            optimization_candidates=(),
        )


def test_geometry_report_service_passes_arguments(tmp_path: Path) -> None:
    model = tmp_path / "model.fbx"
    model.write_bytes(b"fake")
    output = tmp_path / "out"
    reporter = FakeGeometryReporter()
    service = GeometryReportService(reporter)

    report = service.generate(model, output)

    assert report.source_file == model
    assert reporter.calls == [(model, output)]


def test_geometry_report_service_rejects_unsupported_extension(tmp_path: Path) -> None:
    model = tmp_path / "model.txt"
    model.write_text("fake", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected one of"):
        GeometryReportService(FakeGeometryReporter()).generate(model)
