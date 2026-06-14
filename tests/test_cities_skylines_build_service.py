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
        build_folder: Path | None = None,
        optimize: bool = False,
        target_triangle_count: int | None = None,
    ) -> CitiesSkylinesBuildReport:
        internal_folder = blend_file.parent / "build"
        deploy_folder = build_folder or internal_folder
        target = target_triangle_count or profile.default_target_triangles
        return CitiesSkylinesBuildReport(
            source_blend_file=blend_file,
            build_folder=internal_folder,
            deploy_folder=deploy_folder,
            working_blend_file=internal_folder / f"{blend_file.stem}_build.blend",
            fbx_file=internal_folder / f"{blend_file.stem}_cs.fbx",
            diffuse_texture_file=internal_folder / f"{blend_file.stem}_cs_d.png",
            deployed_fbx_file=deploy_folder / f"{blend_file.stem}_cs.fbx",
            deployed_diffuse_texture_file=deploy_folder / f"{blend_file.stem}_cs_d.png",
            report_file=internal_folder / "build_report.json",
            profile_id=profile.profile_id,
            original_triangle_count=10000,
            final_triangle_count=5000 if optimize else 10000,
            target_triangle_count=target,
            optimized=optimize,
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
    assert report.deployed_fbx_file == tmp_path / "build" / "tank_cs.fbx"
    assert not report.optimized
    assert report.final_triangle_count == report.original_triangle_count


def test_build_service_uses_custom_output_folder(tmp_path: Path) -> None:
    blend_file = tmp_path / "tank.blend"
    output_folder = tmp_path / "cities_import"
    blend_file.write_bytes(b"placeholder")
    report = CitiesSkylinesBuildService(FakeBuilder()).build(blend_file, output_folder)

    assert report.build_folder == tmp_path / "build"
    assert report.deploy_folder == output_folder
    assert report.fbx_file == tmp_path / "build" / "tank_cs.fbx"
    assert report.deployed_fbx_file == output_folder / "tank_cs.fbx"


def test_build_service_passes_optimization_target(tmp_path: Path) -> None:
    blend_file = tmp_path / "tank.blend"
    blend_file.write_bytes(b"placeholder")
    report = CitiesSkylinesBuildService(FakeBuilder()).build(
        blend_file,
        optimize=True,
        target_triangle_count=15000,
    )

    assert report.optimized
    assert report.target_triangle_count == 15000


def test_build_service_rejects_missing_file(tmp_path: Path) -> None:
    service = CitiesSkylinesBuildService(FakeBuilder())

    with pytest.raises(FileNotFoundError):
        service.build(tmp_path / "missing.blend")
