from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PreprocessReport:
    source_blend_file: Path
    preprocessed_blend_file: Path
    report_file: Path
    original_triangle_count: int
    preprocessed_triangle_count: int
    removed_triangle_count: int
    reduction_percentage: float
    limited_dissolve_angle_degrees: float
    original_object_count: int = 0
    preprocessed_object_count: int = 0
    joined_mesh_objects: bool = False
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_successful(self) -> bool:
        return not self.errors
