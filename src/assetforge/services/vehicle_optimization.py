from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from assetforge.domain.asset_profile import AssetProfile, AssetProfileRegistry
from assetforge.domain.optimization import VehicleOptimizationReport


class VehicleOptimizer(ABC):
    """Port implemented by infrastructure that can optimize vehicle assets."""

    @abstractmethod
    def optimize(
        self,
        blend_file: Path,
        profile: AssetProfile,
        target_triangle_count: int,
    ) -> VehicleOptimizationReport:
        raise NotImplementedError


class VehicleOptimizationService:
    """Application service used by GUI and CLI callers."""

    def __init__(
        self,
        optimizer: VehicleOptimizer,
        profile_registry: AssetProfileRegistry | None = None,
    ) -> None:
        self._optimizer = optimizer
        self._profile_registry = profile_registry or AssetProfileRegistry()

    def profiles(self) -> tuple[AssetProfile, ...]:
        return self._profile_registry.all()

    def optimize_vehicle(
        self,
        blend_file: Path,
        profile_id: str,
        target_triangle_count: int | None = None,
    ) -> VehicleOptimizationReport:
        if not blend_file.exists():
            raise FileNotFoundError(f"Blend file does not exist: {blend_file}")
        if blend_file.suffix.lower() != ".blend":
            raise ValueError(f"Expected a .blend file, got: {blend_file}")

        profile = self._profile_registry.get(profile_id)
        target = (
            profile.default_target_triangles
            if target_triangle_count is None
            else target_triangle_count
        )
        if target <= 0:
            raise ValueError("Target triangle count must be greater than zero.")

        return self._optimizer.optimize(blend_file, profile, target)
