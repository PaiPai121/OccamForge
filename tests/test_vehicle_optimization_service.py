from pathlib import Path

import pytest

from assetforge.domain.asset_profile import AssetProfile
from assetforge.domain.optimization import VehicleOptimizationReport
from assetforge.services.vehicle_optimization import VehicleOptimizer, VehicleOptimizationService


class FakeOptimizer(VehicleOptimizer):
    def optimize(
        self,
        blend_file: Path,
        profile: AssetProfile,
        target_triangle_count: int,
    ) -> VehicleOptimizationReport:
        return VehicleOptimizationReport(
            source_blend_file=blend_file,
            optimized_blend_file=blend_file.with_name(f"{blend_file.stem}_optimized.blend"),
            report_file=blend_file.with_name(f"{blend_file.stem}_optimized_report.json"),
            profile_id=profile.profile_id,
            target_triangle_count=target_triangle_count,
            original_triangle_count=10000,
            optimized_triangle_count=5000,
            reduction_percentage=50.0,
            body_object="VehicleBody",
            wheel_count=4,
            decimate_ratio=0.5,
            iterations=8,
        )


def test_service_rejects_missing_file(tmp_path: Path) -> None:
    service = VehicleOptimizationService(FakeOptimizer())

    with pytest.raises(FileNotFoundError):
        service.optimize_vehicle(tmp_path / "missing.blend", "generic_vehicle", 5000)


def test_service_rejects_invalid_target(tmp_path: Path) -> None:
    file_path = tmp_path / "asset.blend"
    file_path.write_bytes(b"placeholder")
    service = VehicleOptimizationService(FakeOptimizer())

    with pytest.raises(ValueError):
        service.optimize_vehicle(file_path, "generic_vehicle", 0)


def test_service_uses_profile_default_target(tmp_path: Path) -> None:
    file_path = tmp_path / "asset.blend"
    file_path.write_bytes(b"placeholder")
    service = VehicleOptimizationService(FakeOptimizer())

    report = service.optimize_vehicle(file_path, "generic_vehicle")

    assert report.profile_id == "generic_vehicle"
    assert report.target_triangle_count == 5000

