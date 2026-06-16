from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SimplificationRegion:
    region_id: str
    object_name: str
    original_triangles: int
    optimized_triangles: int
    removed_triangles: int
    reduction_percentage: float


@dataclass(frozen=True, slots=True)
class SimplificationReport:
    source_blend_file: Path
    optimized_blend_file: Path
    report_json_path: Path
    heatmap_image_path: Path
    original_triangle_count: int
    optimized_triangle_count: int
    removed_triangle_count: int
    reduction_percentage: float
    regions: tuple[SimplificationRegion, ...]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_successful(self) -> bool:
        return not self.errors
