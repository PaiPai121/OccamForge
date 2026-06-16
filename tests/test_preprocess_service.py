from pathlib import Path

import pytest

from assetforge.domain.preprocess import PreprocessReport
from assetforge.services.preprocess import PreprocessService


class FakePreprocessor:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, float]] = []

    def preprocess_blend_file(self, blend_file: Path, angle_degrees: float) -> PreprocessReport:
        self.calls.append((blend_file, angle_degrees))
        return PreprocessReport(
            source_blend_file=blend_file,
            preprocessed_blend_file=blend_file.with_name(f"{blend_file.stem}_preprocessed.blend"),
            report_file=blend_file.with_name(f"{blend_file.stem}_preprocessed_report.json"),
            original_triangle_count=100,
            preprocessed_triangle_count=90,
            removed_triangle_count=10,
            reduction_percentage=10.0,
            limited_dissolve_angle_degrees=angle_degrees,
        )


def test_preprocess_service_passes_arguments(tmp_path: Path) -> None:
    blend_file = tmp_path / "vehicle.blend"
    blend_file.write_bytes(b"fake")
    preprocessor = FakePreprocessor()

    report = PreprocessService(preprocessor).preprocess(blend_file, 1.5)

    assert report.limited_dissolve_angle_degrees == 1.5
    assert preprocessor.calls == [(blend_file, 1.5)]


def test_preprocess_service_rejects_unsafe_angle(tmp_path: Path) -> None:
    blend_file = tmp_path / "vehicle.blend"
    blend_file.write_bytes(b"fake")

    with pytest.raises(ValueError, match="between 0 and 5"):
        PreprocessService(FakePreprocessor()).preprocess(blend_file, 8.0)
