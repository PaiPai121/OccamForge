from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from assetforge.domain.analysis import VehicleAnalysisReport


class VehicleAnalyzer(ABC):
    """Port implemented by infrastructure that can analyze vehicle assets."""

    @abstractmethod
    def analyze(self, blend_file: Path) -> VehicleAnalysisReport:
        raise NotImplementedError


class VehicleAnalysisService:
    """Application service used by GUI and CLI callers."""

    def __init__(self, analyzer: VehicleAnalyzer) -> None:
        self._analyzer = analyzer

    def analyze_vehicle(self, blend_file: Path) -> VehicleAnalysisReport:
        if not blend_file.exists():
            raise FileNotFoundError(f"Blend file does not exist: {blend_file}")
        if blend_file.suffix.lower() != ".blend":
            raise ValueError(f"Expected a .blend file, got: {blend_file}")
        return self._analyzer.analyze(blend_file)

