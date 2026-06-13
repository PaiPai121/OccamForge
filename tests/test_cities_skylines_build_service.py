from pathlib import Path

import pytest

from assetforge.domain.asset_profile import AssetProfile
from assetforge.domain.build import CitiesSkylinesBuildReport
from assetforge.services.cities_skylines_build import (
    CitiesSkylinesBuilder,
    CitiesSkylinesBuildService,
)


class FakeBuilder(CitiesSkylinesBuilder):
    def build_cities_skylines_asset(
        self,
        blend_file: Path,
        profile: AssetProfile,
    ) -> CitiesSkylinesBuildReport:
        return CitiesSkylinesBuildReport(
            source_blend_file=blend_file,
            build_folder=blend_file.parent / "build",
            working_blend_file=blend_file.parent / "build" / f"{blend_file.stem}_build.blend",
            fbx_file=blend_file.parent / "build" / f"{blend_file.stem}_cs.fbx",
            diffuse_texture_file=blend_file.parent / "build" / f"{blend_file.stem}_cs_d.png",
            report_file=blend_file.parent / "build" / "build_report.json",
            profile_id=profile.profile_id,
            original_triangle_count=10000,
            final_triangle_count=5000,
            target_triangle_count=profile.default_target_triangles,
            optimized=True,
            body_object="VehicleBody",
            wheel_count=4,
            object_count=5,
        )


def test_build_service_uses_cities_skylines_profile(tmp_path: Path) -> None:
    blend_file = tmp_path / "tank.blend"
    blend_file.write_bytes(b"placeholder")
    report = CitiesSkylinesBuildService(FakeBuilder()).build(blend_file)

    assert report.profile_id == "cities_skylines_vehicle"
    assert report.fbx_file == tmp_path / "build" / "tank_cs.fbx"


def test_build_service_rejects_missing_file(tmp_path: Path) -> None:
    service = CitiesSkylinesBuildService(FakeBuilder())

    with pytest.raises(FileNotFoundError):
        service.build(tmp_path / "missing.blend")
