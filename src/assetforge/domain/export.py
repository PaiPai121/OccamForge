from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class VehicleExportReport:
    """Result produced by a vehicle export operation."""

    source_blend_file: Path
    export_blend_file: Path
    fbx_file: Path
    profile_id: str
    triangle_count: int
    wheel_count: int
    object_count: int
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_successful(self) -> bool:
        return not self.errors

