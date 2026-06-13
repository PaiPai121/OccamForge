from pathlib import Path

from assetforge.domain.optimization import VehicleOptimizationReport
from assetforge.models.optimization_dto import (
    optimization_report_from_dict,
    optimization_report_to_dict,
)


def test_optimization_report_round_trip() -> None:
    report = VehicleOptimizationReport(
        source_blend_file=Path("tank.blend"),
        optimized_blend_file=Path("tank_optimized.blend"),
        report_file=Path("tank_optimized_report.json"),
        profile_id="generic_vehicle",
        target_triangle_count=5000,
        original_triangle_count=10000,
        optimized_triangle_count=5000,
        reduction_percentage=50.0,
        body_object="VehicleBody",
        wheel_count=4,
        decimate_ratio=0.5,
        iterations=8,
        warnings=("inferred body",),
        errors=(),
    )

    restored = optimization_report_from_dict(optimization_report_to_dict(report))

    assert restored == report

