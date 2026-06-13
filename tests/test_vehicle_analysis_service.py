from pathlib import Path

import pytest

from assetforge.domain.analysis import VehicleAnalysisReport
from assetforge.services.vehicle_analysis import VehicleAnalyzer, VehicleAnalysisService


class FakeAnalyzer(VehicleAnalyzer):
    def analyze(self, blend_file: Path) -> VehicleAnalysisReport:
        return VehicleAnalysisReport(
            blend_file=blend_file,
            has_vehicle_body=True,
            wheel_count=4,
            object_count=5,
            vertex_count=10,
            triangle_count=20,
        )


def test_service_rejects_missing_file(tmp_path: Path) -> None:
    service = VehicleAnalysisService(FakeAnalyzer())

    with pytest.raises(FileNotFoundError):
        service.analyze_vehicle(tmp_path / "missing.blend")


def test_service_rejects_non_blend_file(tmp_path: Path) -> None:
    file_path = tmp_path / "asset.txt"
    file_path.write_text("not a blend", encoding="utf-8")
    service = VehicleAnalysisService(FakeAnalyzer())

    with pytest.raises(ValueError):
        service.analyze_vehicle(file_path)


def test_service_delegates_valid_blend_file(tmp_path: Path) -> None:
    file_path = tmp_path / "asset.blend"
    file_path.write_bytes(b"placeholder")
    service = VehicleAnalysisService(FakeAnalyzer())

    report = service.analyze_vehicle(file_path)

    assert report.blend_file == file_path
    assert report.has_vehicle_body is True
    assert report.wheel_count == 4

