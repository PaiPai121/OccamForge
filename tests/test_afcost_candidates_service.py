from __future__ import annotations

from pathlib import Path

import pytest

from assetforge.services.afcost_candidates import AFCostCandidateService


class FakeGenerator:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, Path]] = []

    def generate_afcost_candidates(self, source_file: Path, output_directory: Path) -> dict[str, object]:
        self.calls.append((source_file, output_directory))
        return {"input": str(source_file), "output_directory": str(output_directory), "candidates": []}


def test_afcost_candidate_service_uses_default_output_directory(tmp_path: Path) -> None:
    source = tmp_path / "model.blend"
    source.write_bytes(b"blend")
    generator = FakeGenerator()

    report = AFCostCandidateService(generator).generate(source)

    assert generator.calls == [(source, tmp_path / "afcost_candidates")]
    assert report["output_directory"] == str(tmp_path / "afcost_candidates")


def test_afcost_candidate_service_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        AFCostCandidateService(FakeGenerator()).generate(tmp_path / "missing.blend")
