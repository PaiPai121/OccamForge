from pathlib import Path

import pytest

from assetforge.domain.asset_profile import AssetProfile
from assetforge.domain.export import VehicleExportReport
from assetforge.services.vehicle_export import VehicleExporter, VehicleExportService


class FakeExporter(VehicleExporter):
    def __init__(self) -> None:
        self.export_blend_file: Path | None = None
        self.output_fbx_file: Path | None = None
        self.used_strict_export = False

    def export_fbx(
        self,
        source_blend_file: Path,
        export_blend_file: Path,
        output_fbx_file: Path,
        profile: AssetProfile,
    ) -> VehicleExportReport:
        self.export_blend_file = export_blend_file
        self.output_fbx_file = output_fbx_file
        return VehicleExportReport(
            source_blend_file=source_blend_file,
            export_blend_file=export_blend_file,
            fbx_file=output_fbx_file,
            profile_id=profile.profile_id,
            triangle_count=5000,
            wheel_count=4,
            object_count=5,
        )

    def export_strict_fbx(
        self,
        source_blend_file: Path,
        export_blend_file: Path,
        output_fbx_file: Path,
        profile: AssetProfile,
    ) -> VehicleExportReport:
        self.used_strict_export = True
        self.export_blend_file = export_blend_file
        self.output_fbx_file = output_fbx_file
        return VehicleExportReport(
            source_blend_file=source_blend_file,
            export_blend_file=export_blend_file,
            fbx_file=output_fbx_file,
            profile_id=profile.profile_id,
            triangle_count=5000,
            wheel_count=0,
            object_count=1,
        )


def test_service_uses_optimized_blend_when_available(tmp_path: Path) -> None:
    source = tmp_path / "tank.blend"
    optimized = tmp_path / "tank_optimized.blend"
    source.write_bytes(b"source")
    optimized.write_bytes(b"optimized")
    exporter = FakeExporter()
    service = VehicleExportService(exporter)

    report = service.export_fbx(source)

    assert report.export_blend_file == optimized
    assert report.fbx_file == tmp_path / "tank_cs.fbx"
    assert exporter.export_blend_file == optimized
    assert exporter.used_strict_export is True


def test_service_exports_selected_file_when_no_optimized_blend(tmp_path: Path) -> None:
    source = tmp_path / "tank.blend"
    source.write_bytes(b"source")
    exporter = FakeExporter()
    service = VehicleExportService(exporter)

    report = service.export_fbx(source)

    assert report.export_blend_file == source
    assert exporter.used_strict_export is True


def test_service_rejects_missing_file(tmp_path: Path) -> None:
    service = VehicleExportService(FakeExporter())

    with pytest.raises(FileNotFoundError):
        service.export_fbx(tmp_path / "missing.blend")


def test_service_exports_strict_single_mesh_experiment(tmp_path: Path) -> None:
    source = tmp_path / "tank.blend"
    optimized = tmp_path / "tank_optimized.blend"
    source.write_bytes(b"source")
    optimized.write_bytes(b"optimized")
    exporter = FakeExporter()
    service = VehicleExportService(exporter)

    report = service.export_strict_fbx(source)

    assert report.profile_id == "cities_skylines_vehicle_strict"
    assert report.export_blend_file == optimized
    assert report.fbx_file == tmp_path / "tank_cs_strict.fbx"
    assert report.object_count == 1
