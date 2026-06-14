from pathlib import Path

from assetforge.domain.analysis import VehicleAnalysisReport, VehicleObjectSummary
from assetforge.models.analysis_dto import report_from_dict, report_to_dict


def test_report_round_trip() -> None:
    report = VehicleAnalysisReport(
        blend_file=Path("RhinoTank.blend"),
        has_vehicle_body=True,
        wheel_count=4,
        object_count=5,
        vertex_count=100,
        triangle_count=200,
        preview_mesh_path=Path("previews/RhinoTank_viewport.obj"),
        objects=(
            VehicleObjectSummary(
                name="VehicleBody",
                vertex_count=80,
                triangle_count=160,
                is_body=True,
            ),
        ),
        warnings=("low wheel count",),
        errors=(),
    )

    payload = report_to_dict(report)
    restored = report_from_dict(payload)

    assert restored == report
