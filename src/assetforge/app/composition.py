from __future__ import annotations

from dataclasses import dataclass

from assetforge.blender.locator import BlenderLocator
from assetforge.blender.executor import BlenderBackgroundExecutor
from assetforge.blender.service import BlenderVehicleService
from assetforge.core.config import AssetForgeConfig, UserConfigStore
from assetforge.services.blender_configuration import BlenderConfigurationService
from assetforge.services.model_preview import ModelPreviewService
from assetforge.services.vehicle_analysis import VehicleAnalysisService
from assetforge.services.vehicle_export import VehicleExportService
from assetforge.services.vehicle_optimization import VehicleOptimizationService
from assetforge.services.optimization_preview import OptimizationPreviewService
from assetforge.services.real_optimization_preview import RealOptimizationPreviewService
from assetforge.services.vehicle_validation import VehicleValidationService
from assetforge.services.cities_skylines_build import CitiesSkylinesBuildService


@dataclass(frozen=True, slots=True)
class AppServices:
    vehicle_analysis: VehicleAnalysisService
    vehicle_optimization: VehicleOptimizationService
    vehicle_export: VehicleExportService
    vehicle_validation: VehicleValidationService
    cities_skylines_build: CitiesSkylinesBuildService
    optimization_preview: OptimizationPreviewService
    real_optimization_preview: RealOptimizationPreviewService
    model_preview: ModelPreviewService
    blender_configuration: BlenderConfigurationService


def build_app_services(config: AssetForgeConfig) -> AppServices:
    config_store = UserConfigStore(config.user_config_path)
    locator = BlenderLocator(config_store, explicit_executable=config.blender_executable)
    executor = BlenderBackgroundExecutor(config, locator)
    blender_service = BlenderVehicleService(executor)
    return AppServices(
        vehicle_analysis=VehicleAnalysisService(blender_service),
        vehicle_optimization=VehicleOptimizationService(blender_service),
        vehicle_export=VehicleExportService(blender_service),
        vehicle_validation=VehicleValidationService(blender_service),
        cities_skylines_build=CitiesSkylinesBuildService(blender_service),
        optimization_preview=OptimizationPreviewService(),
        real_optimization_preview=RealOptimizationPreviewService(blender_service),
        model_preview=ModelPreviewService(blender_service),
        blender_configuration=BlenderConfigurationService(locator, config_store),
    )


def build_vehicle_analysis_service(config: AssetForgeConfig) -> VehicleAnalysisService:
    return build_app_services(config).vehicle_analysis
