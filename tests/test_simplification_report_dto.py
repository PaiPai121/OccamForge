from pathlib import Path

from assetforge.domain.simplification_report import SimplificationRegion, SimplificationReport
from assetforge.models.simplification_report_dto import (
    simplification_report_from_dict,
    simplification_report_to_dict,
)


def test_simplification_report_dto_round_trip() -> None:
    report = SimplificationReport(
        source_blend_file=Path("tank.blend"),
        optimized_blend_file=Path("tank_optimized.blend"),
        report_json_path=Path("simplification_reports/simplification_report.json"),
        heatmap_image_path=Path("simplification_reports/simplification_heatmap.png"),
        original_triangle_count=1000,
        optimized_triangle_count=600,
        removed_triangle_count=400,
        reduction_percentage=40.0,
        regions=(
            SimplificationRegion(
                region_id="cell_1_2_3",
                object_name="VehicleBody",
                original_triangles=100,
                optimized_triangles=25,
                removed_triangles=75,
                reduction_percentage=75.0,
            ),
        ),
        warnings=("warning",),
    )

    payload = simplification_report_to_dict(report)
    restored = simplification_report_from_dict(payload)

    assert restored.source_blend_file == report.source_blend_file
    assert restored.optimized_triangle_count == 600
    assert restored.regions[0].removed_triangles == 75
    assert restored.warnings == ("warning",)
