from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from assetforge.domain.asset_profile import AssetProfile, AssetProfileRegistry
from assetforge.domain.build import CitiesSkylinesBuildReport


class CitiesSkylinesBuilder(ABC):
    """Port implemented by infrastructure that can build a CS asset package."""

    @abstractmethod
    def build_cities_skylines_asset(
        self,
        blend_file: Path,
        profile: AssetProfile,
    ) -> CitiesSkylinesBuildReport:
        raise NotImplementedError


class CitiesSkylinesBuildService:
    """Application service for one-click Cities Skylines vehicle builds."""

    def __init__(
        self,
        builder: CitiesSkylinesBuilder,
        profile_registry: AssetProfileRegistry | None = None,
    ) -> None:
        self._builder = builder
        self._profile_registry = profile_registry or AssetProfileRegistry()

    def build(self, blend_file: Path) -> CitiesSkylinesBuildReport:
        if not blend_file.exists():
            raise FileNotFoundError(f"Blend file does not exist: {blend_file}")
        if blend_file.suffix.lower() != ".blend":
            raise ValueError(f"Expected a .blend file, got: {blend_file}")
        profile = self._profile_registry.get("cities_skylines_vehicle")
        return self._builder.build_cities_skylines_asset(blend_file, profile)
