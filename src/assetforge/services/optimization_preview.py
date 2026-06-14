from __future__ import annotations

from assetforge.domain.asset_profile import AssetProfile, AssetProfileRegistry
from assetforge.domain.optimization_preview import (
    OptimizationPreviewOption,
    OptimizationPreviewReport,
)


class OptimizationPreviewService:
    """Estimates optimization outcomes for user decision-making."""

    DEFAULT_TARGETS = (5000, 10000, 15000, 25000)

    def __init__(self, profile_registry: AssetProfileRegistry | None = None) -> None:
        self._profile_registry = profile_registry or AssetProfileRegistry()

    def preview(
        self,
        original_triangle_count: int,
        profile_id: str = "cities_skylines_vehicle",
        targets: tuple[int, ...] = DEFAULT_TARGETS,
    ) -> OptimizationPreviewReport:
        if original_triangle_count <= 0:
            raise ValueError("Original triangle count must be greater than zero.")
        profile = self._profile_registry.get(profile_id)
        options = tuple(
            self._option(original_triangle_count, target, profile)
            for target in targets
            if target > 0
        )
        return OptimizationPreviewReport(
            original_triangle_count=original_triangle_count,
            options=options,
        )

    def _option(
        self,
        original_triangle_count: int,
        target_triangle_count: int,
        profile: AssetProfile,
    ) -> OptimizationPreviewOption:
        estimated = min(original_triangle_count, target_triangle_count)
        reduction = round(
            ((original_triangle_count - estimated) / original_triangle_count) * 100.0,
            2,
        )
        score = self._score(estimated, profile)
        return OptimizationPreviewOption(
            target_triangle_count=target_triangle_count,
            estimated_triangle_count=estimated,
            reduction_percentage=reduction,
            estimated_compatibility_score=score,
            rating=self._rating(score),
        )

    def _score(self, triangle_count: int, profile: AssetProfile) -> int:
        if triangle_count > profile.critical_triangle_count:
            return 40
        if triangle_count > profile.warning_triangle_count:
            return 65
        if triangle_count >= profile.preferred_triangle_count:
            return 85
        return 95

    def _rating(self, score: int) -> str:
        if score < 50:
            return "Critical"
        if score < 75:
            return "Warning"
        if score < 90:
            return "Good"
        return "Excellent"
