from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from assetforge.domain.asset_profile import AssetProfile, AssetProfileRegistry
from assetforge.domain.export import VehicleExportReport


class VehicleExporter(ABC):
    """Port implemented by infrastructure that can export vehicle assets."""

    @abstractmethod
    def export_fbx(
        self,
        source_blend_file: Path,
        export_blend_file: Path,
        output_fbx_file: Path,
        profile: AssetProfile,
    ) -> VehicleExportReport:
        raise NotImplementedError

    def export_strict_fbx(
        self,
        source_blend_file: Path,
        export_blend_file: Path,
        output_fbx_file: Path,
        profile: AssetProfile,
    ) -> VehicleExportReport:
        raise NotImplementedError


class VehicleExportService:
    """Application service for game-friendly vehicle exports."""

    def __init__(
        self,
        exporter: VehicleExporter,
        profile_registry: AssetProfileRegistry | None = None,
    ) -> None:
        self._exporter = exporter
        self._profile_registry = profile_registry or AssetProfileRegistry()

    def export_fbx(self, blend_file: Path, profile_id: str = "cities_skylines_vehicle") -> VehicleExportReport:
        if not blend_file.exists():
            raise FileNotFoundError(f"Blend file does not exist: {blend_file}")
        if blend_file.suffix.lower() != ".blend":
            raise ValueError(f"Expected a .blend file, got: {blend_file}")

        profile = self._profile_registry.get(profile_id)
        export_blend = self.preferred_export_blend(blend_file)
        output_fbx = blend_file.with_name(f"{blend_file.stem}_cs.fbx")
        if profile.profile_id in {
            "cities_skylines_vehicle",
            "cities_skylines_vehicle_strict",
        }:
            return self._exporter.export_strict_fbx(blend_file, export_blend, output_fbx, profile)
        return self._exporter.export_fbx(blend_file, export_blend, output_fbx, profile)

    def export_strict_fbx(
        self,
        blend_file: Path,
        profile_id: str = "cities_skylines_vehicle_strict",
    ) -> VehicleExportReport:
        if not blend_file.exists():
            raise FileNotFoundError(f"Blend file does not exist: {blend_file}")
        if blend_file.suffix.lower() != ".blend":
            raise ValueError(f"Expected a .blend file, got: {blend_file}")

        profile = self._profile_registry.get(profile_id)
        export_blend = self.preferred_export_blend(blend_file)
        output_fbx = blend_file.with_name(f"{blend_file.stem}_cs_strict.fbx")
        return self._exporter.export_strict_fbx(blend_file, export_blend, output_fbx, profile)

    def preferred_export_blend(self, blend_file: Path) -> Path:
        if blend_file.stem.endswith("_optimized"):
            return blend_file
        optimized = blend_file.with_name(f"{blend_file.stem}_optimized{blend_file.suffix}")
        return optimized if optimized.exists() else blend_file
