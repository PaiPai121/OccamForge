from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from assetforge.domain.asset_profile import AssetProfile, AssetProfileRegistry
from assetforge.domain.real_optimization_preview import RealOptimizationPreviewReport


class LocalSimplifier(ABC):
    """Port implemented by infrastructure that can run local edge-collapse simplification."""

    @abstractmethod
    def generate_local_simplification_preview(
        self,
        blend_file: Path,
        profile: AssetProfile,
        target_triangle_count: int,
        output_directory: Path,
        combo_candidate: str = "auto",
    ) -> RealOptimizationPreviewReport:
        raise NotImplementedError


class LocalSimplificationService:
    """Runs the local collapse executor using combo ranking and QEM placement."""

    def __init__(
        self,
        simplifier: LocalSimplifier,
        profile_registry: AssetProfileRegistry | None = None,
    ) -> None:
        self._simplifier = simplifier
        self._profile_registry = profile_registry or AssetProfileRegistry()

    def generate(
        self,
        blend_file: Path,
        profile_id: str = "cities_skylines_vehicle",
        target_triangle_count: int = 5000,
        output_directory: Path | None = None,
        combo_candidate: str = "auto",
    ) -> RealOptimizationPreviewReport:
        if not blend_file.exists():
            raise FileNotFoundError(f"Blend file does not exist: {blend_file}")
        if blend_file.suffix.lower() != ".blend":
            raise ValueError(f"Expected a .blend file, got: {blend_file}")
        if target_triangle_count <= 0:
            raise ValueError("Target triangle count must be greater than zero.")

        profile = self._profile_registry.get(profile_id)
        preview_directory = output_directory or blend_file.parent / "previews"
        return self._simplifier.generate_local_simplification_preview(
            blend_file,
            profile,
            target_triangle_count,
            preview_directory,
            combo_candidate,
        )
