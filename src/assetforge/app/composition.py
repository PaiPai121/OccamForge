from __future__ import annotations

from dataclasses import dataclass

from assetforge.blender.locator import BlenderLocator
from assetforge.blender.executor import BlenderBackgroundExecutor
from assetforge.blender.service import BlenderVehicleService
from assetforge.core.config import AssetForgeConfig, UserConfigStore
from assetforge.services.blender_configuration import BlenderConfigurationService
from assetforge.services.vehicle_analysis import VehicleAnalysisService
from assetforge.services.vehicle_optimization import VehicleOptimizationService


@dataclass(frozen=True, slots=True)
class AppServices:
    vehicle_analysis: VehicleAnalysisService
    vehicle_optimization: VehicleOptimizationService
    blender_configuration: BlenderConfigurationService


def build_app_services(config: AssetForgeConfig) -> AppServices:
    config_store = UserConfigStore(config.user_config_path)
    locator = BlenderLocator(config_store, explicit_executable=config.blender_executable)
    executor = BlenderBackgroundExecutor(config, locator)
    blender_service = BlenderVehicleService(executor)
    return AppServices(
        vehicle_analysis=VehicleAnalysisService(blender_service),
        vehicle_optimization=VehicleOptimizationService(blender_service),
        blender_configuration=BlenderConfigurationService(locator, config_store),
    )


def build_vehicle_analysis_service(config: AssetForgeConfig) -> VehicleAnalysisService:
    return build_app_services(config).vehicle_analysis
