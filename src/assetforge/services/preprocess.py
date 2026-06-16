from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from assetforge.domain.preprocess import PreprocessReport


class AssetPreprocessor(ABC):
    @abstractmethod
    def preprocess_blend_file(
        self,
        blend_file: Path,
        angle_degrees: float,
    ) -> PreprocessReport:
        raise NotImplementedError


class PreprocessService:
    """Runs conservative mesh cleanup before optional optimization."""

    def __init__(self, preprocessor: AssetPreprocessor) -> None:
        self._preprocessor = preprocessor

    def preprocess(
        self,
        blend_file: Path,
        angle_degrees: float = 1.0,
    ) -> PreprocessReport:
        if not blend_file.exists():
            raise FileNotFoundError(f"Blend file does not exist: {blend_file}")
        if blend_file.suffix.lower() != ".blend":
            raise ValueError(f"Expected a .blend file, got: {blend_file}")
        if angle_degrees <= 0 or angle_degrees > 5:
            raise ValueError("Safe preprocess angle must be between 0 and 5 degrees.")
        return self._preprocessor.preprocess_blend_file(blend_file, angle_degrees)
