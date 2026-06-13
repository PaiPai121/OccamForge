from pathlib import Path

from assetforge.domain.export import VehicleExportReport
from assetforge.models.export_dto import export_report_from_dict, export_report_to_dict


def test_export_report_round_trip() -> None:
    report = VehicleExportReport(
        source_blend_file=Path("tank.blend"),
        export_blend_file=Path("tank_optimized.blend"),
        fbx_file=Path("tank_cs.fbx"),
        profile_id="cities_skylines_vehicle",
        triangle_count=5000,
        wheel_count=4,
        object_count=5,
        warnings=("inferred body",),
        errors=(),
    )

    restored = export_report_from_dict(export_report_to_dict(report))

    assert restored == report

