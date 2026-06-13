from __future__ import annotations

from pathlib import Path

from assetforge.blender.commands import BlenderVehicleOperations
from assetforge.blender.executor import BlenderBackgroundExecutor
from assetforge.domain.asset_profile import AssetProfile
from assetforge.domain.analysis import VehicleAnalysisReport
from assetforge.domain.optimization import VehicleOptimizationReport
from assetforge.models.analysis_dto import report_from_dict
from assetforge.models.optimization_dto import optimization_report_from_dict
from assetforge.services.vehicle_analysis import VehicleAnalyzer
from assetforge.services.vehicle_optimization import VehicleOptimizer


class BlenderVehicleService(BlenderVehicleOperations, VehicleAnalyzer, VehicleOptimizer):
    """Production adapter for vehicle operations implemented in Blender."""

    def __init__(self, executor: BlenderBackgroundExecutor) -> None:
        self._executor = executor

    def analyze(self, blend_file: Path) -> VehicleAnalysisReport:
        return self.analyze_vehicle(blend_file)

    def analyze_vehicle(self, blend_file: Path) -> VehicleAnalysisReport:
        script_path = Path(__file__).parent / "scripts" / "analyze_vehicle.py"
        payload = self._executor.run_script(script_path, ["--blend-file", str(blend_file)])
        return report_from_dict(payload)

    def optimize(
        self,
        blend_file: Path,
        profile: AssetProfile,
        target_triangle_count: int,
    ) -> VehicleOptimizationReport:
        return self.optimize_vehicle(blend_file, profile, target_triangle_count)

    def optimize_vehicle(
        self,
        blend_file: Path,
        profile: AssetProfile,
        target_triangle_count: int,
    ) -> VehicleOptimizationReport:
        script_path = Path(__file__).parent / "scripts" / "optimize_vehicle.py"
        payload = self._executor.run_script(
            script_path,
            [
                "--blend-file",
                str(blend_file),
                "--profile-id",
                profile.profile_id,
                "--target-triangles",
                str(target_triangle_count),
                "--minimum-ratio",
                str(profile.minimum_decimate_ratio),
                "--max-iterations",
                str(profile.max_decimation_iterations),
                "--preserve-wheels",
                str(profile.preserve_wheels),
                "--decimate-body-only",
                str(profile.decimate_body_only),
            ],
        )
        return optimization_report_from_dict(payload)
