from __future__ import annotations

from pathlib import Path

from assetforge.blender.commands import BlenderVehicleOperations
from assetforge.blender.executor import BlenderBackgroundExecutor
from assetforge.domain.asset_profile import AssetProfile
from assetforge.domain.analysis import VehicleAnalysisReport
from assetforge.domain.build import CitiesSkylinesBuildReport
from assetforge.domain.export import VehicleExportReport
from assetforge.domain.model_preview import ModelPreviewReport
from assetforge.domain.optimization import VehicleOptimizationReport
from assetforge.domain.real_optimization_preview import RealOptimizationPreviewReport
from assetforge.domain.validation import ValidationReport
from assetforge.models.analysis_dto import report_from_dict
from assetforge.models.build_dto import build_report_from_dict
from assetforge.models.export_dto import export_report_from_dict
from assetforge.models.model_preview_dto import model_preview_report_from_dict
from assetforge.models.optimization_dto import optimization_report_from_dict
from assetforge.models.real_optimization_preview_dto import real_preview_report_from_dict
from assetforge.models.validation_dto import validation_report_from_dict
from assetforge.services.cities_skylines_build import CitiesSkylinesBuilder
from assetforge.services.model_preview import ModelPreviewGenerator
from assetforge.services.real_optimization_preview import RealOptimizationPreviewer
from assetforge.services.vehicle_analysis import VehicleAnalyzer
from assetforge.services.vehicle_export import VehicleExporter
from assetforge.services.vehicle_optimization import VehicleOptimizer
from assetforge.services.vehicle_validation import VehicleValidator


class BlenderVehicleService(
    BlenderVehicleOperations,
    VehicleAnalyzer,
    VehicleOptimizer,
    VehicleExporter,
    VehicleValidator,
    CitiesSkylinesBuilder,
    RealOptimizationPreviewer,
    ModelPreviewGenerator,
):
    """Production adapter for vehicle operations implemented in Blender."""

    def __init__(self, executor: BlenderBackgroundExecutor) -> None:
        self._executor = executor

    def analyze(self, blend_file: Path) -> VehicleAnalysisReport:
        return self.analyze_vehicle(blend_file)

    def analyze_vehicle(self, blend_file: Path) -> VehicleAnalysisReport:
        script_path = Path(__file__).parent / "scripts" / "analyze_vehicle.py"
        preview_mesh_path = blend_file.parent / "previews" / f"{blend_file.stem}_viewport.obj"
        payload = self._executor.run_script(
            script_path,
            [
                "--blend-file",
                str(blend_file),
                "--preview-mesh",
                str(preview_mesh_path),
            ],
        )
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

    def export_fbx(
        self,
        source_blend_file: Path,
        export_blend_file: Path,
        output_fbx_file: Path,
        profile: AssetProfile,
    ) -> VehicleExportReport:
        script_path = Path(__file__).parent / "scripts" / "export_fbx.py"
        payload = self._executor.run_script(
            script_path,
            [
                "--source-blend-file",
                str(source_blend_file),
                "--export-blend-file",
                str(export_blend_file),
                "--output-fbx",
                str(output_fbx_file),
                "--profile-id",
                profile.profile_id,
            ],
        )
        return export_report_from_dict(payload)

    def export_strict_fbx(
        self,
        source_blend_file: Path,
        export_blend_file: Path,
        output_fbx_file: Path,
        profile: AssetProfile,
    ) -> VehicleExportReport:
        script_path = Path(__file__).parent / "scripts" / "export_fbx_strict.py"
        payload = self._executor.run_script(
            script_path,
            [
                "--source-blend-file",
                str(source_blend_file),
                "--export-blend-file",
                str(export_blend_file),
                "--output-fbx",
                str(output_fbx_file),
                "--profile-id",
                profile.profile_id,
            ],
        )
        return export_report_from_dict(payload)

    def validate_vehicle_asset(
        self,
        blend_file: Path,
        profile: AssetProfile,
    ) -> ValidationReport:
        script_path = Path(__file__).parent / "scripts" / "validate_vehicle.py"
        payload = self._executor.run_script(
            script_path,
            [
                "--blend-file",
                str(blend_file),
                "--profile-id",
                profile.profile_id,
                "--preferred-triangles",
                str(profile.preferred_triangle_count),
                "--warning-triangles",
                str(profile.warning_triangle_count),
                "--critical-triangles",
                str(profile.critical_triangle_count),
            ],
        )
        return validation_report_from_dict(payload)

    def build_cities_skylines_asset(
        self,
        blend_file: Path,
        profile: AssetProfile,
        build_folder: Path | None = None,
        optimize: bool = False,
        target_triangle_count: int | None = None,
    ) -> CitiesSkylinesBuildReport:
        script_path = Path(__file__).parent / "scripts" / "build_cities_skylines_asset.py"
        target = target_triangle_count or profile.default_target_triangles
        arguments = [
            "--blend-file",
            str(blend_file),
            "--profile-id",
            profile.profile_id,
            "--target-triangles",
            str(target),
            "--warning-triangles",
            str(profile.warning_triangle_count),
            "--critical-triangles",
            str(profile.critical_triangle_count),
            "--minimum-ratio",
            str(profile.minimum_decimate_ratio),
            "--max-iterations",
            str(profile.max_decimation_iterations),
        ]
        if build_folder is not None:
            arguments.extend(["--deploy-folder", str(build_folder)])
        if optimize:
            arguments.append("--optimize")
        payload = self._executor.run_script(
            script_path,
            arguments,
        )
        return build_report_from_dict(payload)

    def generate_real_optimization_preview(
        self,
        blend_file: Path,
        profile: AssetProfile,
        target_triangle_count: int,
        output_directory: Path,
    ) -> RealOptimizationPreviewReport:
        script_path = Path(__file__).parent / "scripts" / "generate_real_optimization_preview.py"
        payload = self._executor.run_script(
            script_path,
            [
                "--blend-file",
                str(blend_file),
                "--profile-id",
                profile.profile_id,
                "--target-triangles",
                str(target_triangle_count),
                "--output-directory",
                str(output_directory),
                "--minimum-ratio",
                str(profile.minimum_decimate_ratio),
                "--max-iterations",
                str(profile.max_decimation_iterations),
                "--decimate-body-only",
                str(profile.decimate_body_only),
                "--warning-triangles",
                str(profile.warning_triangle_count),
                "--critical-triangles",
                str(profile.critical_triangle_count),
            ],
        )
        return real_preview_report_from_dict(payload)

    def generate_model_preview(
        self,
        blend_file: Path,
        output_directory: Path,
    ) -> ModelPreviewReport:
        script_path = Path(__file__).parent / "scripts" / "generate_model_preview.py"
        payload = self._executor.run_script(
            script_path,
            [
                "--blend-file",
                str(blend_file),
                "--output-directory",
                str(output_directory),
            ],
        )
        return model_preview_report_from_dict(payload)
