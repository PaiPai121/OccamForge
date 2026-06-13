from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from assetforge.domain.asset_profile import AssetProfile
from assetforge.domain.analysis import VehicleAnalysisReport
from assetforge.domain.build import CitiesSkylinesBuildReport
from assetforge.domain.export import VehicleExportReport
from assetforge.domain.optimization import VehicleOptimizationReport
from assetforge.domain.validation import ValidationReport


class BlenderVehicleOperations(ABC):
    """Future-facing Blender operation contract."""

    @abstractmethod
    def analyze_vehicle(self, blend_file: Path) -> VehicleAnalysisReport:
        raise NotImplementedError

    def optimize_vehicle(
        self,
        blend_file: Path,
        profile: AssetProfile,
        target_triangle_count: int,
    ) -> VehicleOptimizationReport:
        raise NotImplementedError("Optimization is not implemented by this adapter.")

    def bake_textures(self, blend_file: Path) -> None:
        raise NotImplementedError("Texture baking is planned for a later phase.")

    def export_fbx(
        self,
        source_blend_file: Path,
        export_blend_file: Path,
        output_fbx_file: Path,
        profile: AssetProfile,
    ) -> VehicleExportReport:
        raise NotImplementedError("FBX export is not implemented by this adapter.")

    def export_strict_fbx(
        self,
        source_blend_file: Path,
        export_blend_file: Path,
        output_fbx_file: Path,
        profile: AssetProfile,
    ) -> VehicleExportReport:
        raise NotImplementedError("Strict FBX export is not implemented by this adapter.")

    def validate_vehicle_asset(
        self,
        blend_file: Path,
        profile: AssetProfile,
    ) -> ValidationReport:
        raise NotImplementedError("Validation is not implemented by this adapter.")

    def build_cities_skylines_asset(
        self,
        blend_file: Path,
        profile: AssetProfile,
    ) -> CitiesSkylinesBuildReport:
        raise NotImplementedError("Cities Skylines build is not implemented by this adapter.")
