from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CitiesSkylinesBuildReport:
    """One-click build output for a Cities Skylines vehicle asset."""

    source_blend_file: Path
    build_folder: Path
    working_blend_file: Path
    fbx_file: Path
    diffuse_texture_file: Path
    report_file: Path
    profile_id: str
    original_triangle_count: int
    final_triangle_count: int
    target_triangle_count: int
    optimized: bool
    body_object: str | None
    wheel_count: int
    object_count: int
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_successful(self) -> bool:
        return not self.errors

