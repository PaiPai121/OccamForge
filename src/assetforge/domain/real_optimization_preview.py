from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RealOptimizationPreviewItem:
    target_triangles: int
    actual_triangles: int
    reduction_percent: float
    compatibility_score: int
    rating: str
    preview_blend_path: Path
    preview_image_path: Path
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_successful(self) -> bool:
        return not self.errors


@dataclass(frozen=True, slots=True)
class RealOptimizationPreviewReport:
    source_blend_file: Path
    output_directory: Path
    original_triangle_count: int
    profile_id: str
    items: tuple[RealOptimizationPreviewItem, ...]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_successful(self) -> bool:
        return not self.errors and all(item.is_successful for item in self.items)
