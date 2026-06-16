from pathlib import Path

from assetforge.domain.preprocess import PreprocessReport
from assetforge.models.preprocess_dto import preprocess_report_from_dict, preprocess_report_to_dict


def test_preprocess_report_dto_round_trip() -> None:
    report = PreprocessReport(
        source_blend_file=Path("tank.blend"),
        preprocessed_blend_file=Path("tank_preprocessed.blend"),
        report_file=Path("tank_preprocessed_report.json"),
        original_triangle_count=1000,
        preprocessed_triangle_count=900,
        removed_triangle_count=100,
        reduction_percentage=10.0,
        limited_dissolve_angle_degrees=1.0,
        warnings=("warning",),
    )

    restored = preprocess_report_from_dict(preprocess_report_to_dict(report))

    assert restored.preprocessed_blend_file == report.preprocessed_blend_file
    assert restored.removed_triangle_count == 100
    assert restored.limited_dissolve_angle_degrees == 1.0
    assert restored.warnings == ("warning",)
