from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OptimizationPreviewOption:
    target_triangle_count: int
    estimated_triangle_count: int
    reduction_percentage: float
    estimated_compatibility_score: int
    rating: str


@dataclass(frozen=True, slots=True)
class OptimizationPreviewReport:
    original_triangle_count: int
    options: tuple[OptimizationPreviewOption, ...]

