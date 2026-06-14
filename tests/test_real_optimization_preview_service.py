from pathlib import Path

import pytest

from assetforge.domain.asset_profile import AssetProfile
from assetforge.domain.real_optimization_preview import RealOptimizationPreviewReport
from assetforge.services.real_optimization_preview import (
    RealOptimizationPreviewService,
    RealOptimizationPreviewer,
)


class FakePreviewer(RealOptimizationPreviewer):
    def __init__(self) -> None:
        self.calls: list[tuple[Path, AssetProfile, int, Path]] = []

    def generate_real_optimization_preview(
        self,
        blend_file: Path,
        profile: AssetProfile,
        target_triangle_count: int,
        output_directory: Path,
    ) -> RealOptimizationPreviewReport:
        self.calls.append((blend_file, profile, target_triangle_count, output_directory))
        return RealOptimizationPreviewReport(
            source_blend_file=blend_file,
            output_directory=output_directory,
            original_triangle_count=0,
            profile_id=profile.profile_id,
            items=(),
        )


def test_real_preview_service_uses_target_and_default_output(tmp_path: Path) -> None:
    blend_file = tmp_path / "tank.blend"
    blend_file.write_bytes(b"placeholder")
    previewer = FakePreviewer()

    report = RealOptimizationPreviewService(previewer).generate(
        blend_file,
        "cities_skylines_vehicle",
        15000,
    )

    assert report.output_directory == tmp_path / "previews"
    assert previewer.calls[0][2] == 15000
    assert previewer.calls[0][1].profile_id == "cities_skylines_vehicle"


def test_real_preview_service_rejects_invalid_target(tmp_path: Path) -> None:
    blend_file = tmp_path / "tank.blend"
    blend_file.write_bytes(b"placeholder")

    with pytest.raises(ValueError, match="Target triangle count"):
        RealOptimizationPreviewService(FakePreviewer()).generate(
            blend_file,
            target_triangle_count=0,
        )
