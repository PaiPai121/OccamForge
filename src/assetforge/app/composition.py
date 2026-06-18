from __future__ import annotations

from dataclasses import dataclass

from assetforge.blender.locator import BlenderLocator
from assetforge.blender.executor import BlenderBackgroundExecutor
from assetforge.blender.service import BlenderVehicleService
from assetforge.core.config import AssetForgeConfig, UserConfigStore
from assetforge.services.blender_configuration import BlenderConfigurationService
from assetforge.services.afcost_candidates import AFCostCandidateService
from assetforge.services.geometry_report import GeometryReportService
from assetforge.services.model_preview import ModelPreviewService
from assetforge.services.vehicle_analysis import VehicleAnalysisService
from assetforge.services.vehicle_export import VehicleExportService
from assetforge.services.vehicle_optimization import VehicleOptimizationService
from assetforge.services.optimization_preview import OptimizationPreviewService
from assetforge.services.preprocess import PreprocessService
from assetforge.services.qem_heatmap import QemHeatmapService
from assetforge.services.real_optimization_preview import RealOptimizationPreviewService
from assetforge.services.scale_analysis import ScaleAnalysisService
from assetforge.services.simplification_report import SimplificationReportService
from assetforge.services.vehicle_validation import VehicleValidationService
from assetforge.services.cities_skylines_build import CitiesSkylinesBuildService


@dataclass(frozen=True, slots=True)
class AppServices:
    vehicle_analysis: VehicleAnalysisService
    vehicle_optimization: VehicleOptimizationService
    preprocess: PreprocessService
    vehicle_export: VehicleExportService
    vehicle_validation: VehicleValidationService
    cities_skylines_build: CitiesSkylinesBuildService
    optimization_preview: OptimizationPreviewService
    real_optimization_preview: RealOptimizationPreviewService
    model_preview: ModelPreviewService
    geometry_report: GeometryReportService
    simplification_report: SimplificationReportService
    qem_heatmap: QemHeatmapService
    scale_analysis: ScaleAnalysisService
    afcost_candidates: AFCostCandidateService
    blender_configuration: BlenderConfigurationService


def build_app_services(config: AssetForgeConfig) -> AppServices:
    config_store = UserConfigStore(config.user_config_path)
    locator = BlenderLocator(config_store, explicit_executable=config.blender_executable)
    executor = BlenderBackgroundExecutor(config, locator)
    blender_service = BlenderVehicleService(executor)
    return AppServices(
        vehicle_analysis=VehicleAnalysisService(blender_service),
        vehicle_optimization=VehicleOptimizationService(blender_service),
        preprocess=PreprocessService(blender_service),
        vehicle_export=VehicleExportService(blender_service),
        vehicle_validation=VehicleValidationService(blender_service),
        cities_skylines_build=CitiesSkylinesBuildService(blender_service),
        optimization_preview=OptimizationPreviewService(),
        real_optimization_preview=RealOptimizationPreviewService(blender_service),
        model_preview=ModelPreviewService(blender_service),
        geometry_report=GeometryReportService(blender_service),
        simplification_report=SimplificationReportService(blender_service),
        qem_heatmap=QemHeatmapService(blender_service),
        scale_analysis=ScaleAnalysisService(blender_service),
        afcost_candidates=AFCostCandidateService(blender_service),
        blender_configuration=BlenderConfigurationService(locator, config_store),
    )


def build_vehicle_analysis_service(config: AssetForgeConfig) -> VehicleAnalysisService:
    return build_app_services(config).vehicle_analysis
