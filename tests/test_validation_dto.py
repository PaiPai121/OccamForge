from pathlib import Path

from assetforge.domain.validation import ImportReadiness, ValidationIssue, ValidationReport
from assetforge.models.validation_dto import validation_report_from_dict, validation_report_to_dict


def test_validation_report_round_trip() -> None:
    report = ValidationReport(
        blend_file=Path("tank.blend"),
        report_file=Path("validation_report.json"),
        profile_id="cities_skylines_vehicle",
        triangle_count=4000,
        wheel_count=4,
        object_count=5,
        blender_path=Path("blender.exe"),
        body_object="VehicleBody",
        wheel_objects=("Wheel_001",),
        unknown_objects=("Antenna",),
        unapplied_transform_objects=(),
        auto_texture_candidate_objects=("Antenna",),
        missing_lods=("lod1", "lod2"),
        score=80,
        rating="Good",
        export_ready=True,
        import_readiness=ImportReadiness(
            package_folder=Path("build"),
            fbx_file=Path("build/tank_cs.fbx"),
            diffuse_texture_file=Path("build/tank_cs_d.png"),
            build_report_file=Path("build/build_report.json"),
            files_ready=True,
            blender_fbx_import_ready=True,
            import_ready=True,
            cities_skylines_editor_status="manual_required",
            manual_steps=("Open Asset Editor",),
        ),
        issues=(ValidationIssue("missing_lods", "warning", "Missing LODs"),),
        messages=("Missing LODs",),
    )

    restored = validation_report_from_dict(validation_report_to_dict(report))

    assert restored == report
