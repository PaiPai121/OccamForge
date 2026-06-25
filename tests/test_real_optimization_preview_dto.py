from pathlib import Path

from assetforge.domain.real_optimization_preview import (
    RealOptimizationPreviewItem,
    RealOptimizationPreviewReport,
)
from assetforge.models.real_optimization_preview_dto import (
    real_preview_report_from_dict,
    real_preview_report_to_dict,
)


def test_real_preview_report_round_trip() -> None:
    report = RealOptimizationPreviewReport(
        source_blend_file=Path("tank.blend"),
        output_directory=Path("previews"),
        original_triangle_count=62656,
        profile_id="cities_skylines_vehicle",
        items=(
            RealOptimizationPreviewItem(
                target_triangles=5000,
                actual_triangles=4984,
                reduction_percent=92.04,
                compatibility_score=85,
                rating="Good",
                preview_blend_path=Path("previews/preview_5000.blend"),
                preview_image_path=Path("previews/preview_5000.png"),
                preview_mesh_path=Path("previews/preview_5000.obj"),
                warnings=("body inferred",),
                errors=(),
            ),
        ),
        warnings=(),
        errors=(),
    )

    restored = real_preview_report_from_dict(real_preview_report_to_dict(report))

    assert restored == report
