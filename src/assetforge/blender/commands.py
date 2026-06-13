from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from assetforge.domain.asset_profile import AssetProfile
from assetforge.domain.analysis import VehicleAnalysisReport
from assetforge.domain.optimization import VehicleOptimizationReport


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

    def export_fbx(self, blend_file: Path, output_file: Path) -> None:
        raise NotImplementedError("FBX export is planned for a later phase.")
