from pathlib import Path

from assetforge.domain.build import CitiesSkylinesBuildReport
from assetforge.models.build_dto import build_report_from_dict, build_report_to_dict


def test_build_report_round_trip() -> None:
    report = CitiesSkylinesBuildReport(
        source_blend_file=Path("tank.blend"),
        build_folder=Path("build"),
        working_blend_file=Path("build/tank_build.blend"),
        fbx_file=Path("build/tank_cs.fbx"),
        diffuse_texture_file=Path("build/tank_cs_d.png"),
        report_file=Path("build/build_report.json"),
        profile_id="cities_skylines_vehicle",
        original_triangle_count=10000,
        final_triangle_count=5000,
        target_triangle_count=5000,
        optimized=True,
        body_object="VehicleBody",
        wheel_count=4,
        object_count=5,
        warnings=("inferred body",),
        errors=(),
    )

    restored = build_report_from_dict(build_report_to_dict(report))

    assert restored == report

