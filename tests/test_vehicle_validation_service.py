from pathlib import Path

import pytest

from assetforge.domain.asset_profile import AssetProfile
from assetforge.domain.validation import ImportReadiness, ValidationReport
from assetforge.services.vehicle_validation import VehicleValidationService, VehicleValidator


class FakeValidator(VehicleValidator):
    def validate_vehicle_asset(self, blend_file: Path, profile: AssetProfile) -> ValidationReport:
        return ValidationReport(
            blend_file=blend_file,
            report_file=blend_file.with_name("validation_report.json"),
            profile_id=profile.profile_id,
            triangle_count=4000,
            wheel_count=4,
            object_count=5,
            blender_path=Path("blender.exe"),
            body_object="VehicleBody",
            wheel_objects=("Wheel_001",),
            unknown_objects=(),
            unapplied_transform_objects=(),
            auto_texture_candidate_objects=(),
            missing_lods=(),
            score=95,
            rating="Excellent",
            export_ready=True,
            import_readiness=ImportReadiness(
                package_folder=blend_file.parent / "build",
                fbx_file=blend_file.parent / "build" / "tank_cs.fbx",
                diffuse_texture_file=blend_file.parent / "build" / "tank_cs_d.png",
                build_report_file=blend_file.parent / "build" / "build_report.json",
                files_ready=True,
                blender_fbx_import_ready=True,
                import_ready=True,
                cities_skylines_editor_status="manual_required",
                manual_steps=("Open Asset Editor",),
            ),
        )


def test_validation_service_delegates_valid_blend_file(tmp_path: Path) -> None:
    blend_file = tmp_path / "tank.blend"
    blend_file.write_bytes(b"placeholder")
    service = VehicleValidationService(FakeValidator())

    report = service.validate_vehicle(blend_file, "cities_skylines_vehicle")

    assert report.export_ready is True
    assert report.profile_id == "cities_skylines_vehicle"


def test_validation_service_rejects_missing_file(tmp_path: Path) -> None:
    service = VehicleValidationService(FakeValidator())

    with pytest.raises(FileNotFoundError):
        service.validate_vehicle(tmp_path / "missing.blend")
