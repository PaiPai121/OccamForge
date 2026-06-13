from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from assetforge.domain.asset_profile import AssetProfile, AssetProfileRegistry
from assetforge.domain.validation import ValidationReport


class VehicleValidator(ABC):
    """Port implemented by infrastructure that can validate vehicle assets."""

    @abstractmethod
    def validate_vehicle_asset(
        self,
        blend_file: Path,
        profile: AssetProfile,
    ) -> ValidationReport:
        raise NotImplementedError


class VehicleValidationService:
    """Application service for game-readiness validation."""

    def __init__(
        self,
        validator: VehicleValidator,
        profile_registry: AssetProfileRegistry | None = None,
    ) -> None:
        self._validator = validator
        self._profile_registry = profile_registry or AssetProfileRegistry()

    def validate_vehicle(
        self,
        blend_file: Path,
        profile_id: str = "cities_skylines_vehicle",
    ) -> ValidationReport:
        if not blend_file.exists():
            raise FileNotFoundError(f"Blend file does not exist: {blend_file}")
        if blend_file.suffix.lower() != ".blend":
            raise ValueError(f"Expected a .blend file, got: {blend_file}")
        profile = self._profile_registry.get(profile_id)
        return self._validator.validate_vehicle_asset(blend_file, profile)
