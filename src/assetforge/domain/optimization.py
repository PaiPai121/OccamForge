from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class VehicleOptimizationReport:
    """Result produced by vehicle optimization."""

    source_blend_file: Path
    optimized_blend_file: Path
    report_file: Path
    profile_id: str
    target_triangle_count: int
    original_triangle_count: int
    optimized_triangle_count: int
    reduction_percentage: float
    body_object: str | None
    wheel_count: int
    decimate_ratio: float
    iterations: int
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_successful(self) -> bool:
        return not self.errors
