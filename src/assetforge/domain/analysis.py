from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class VehicleObjectSummary:
    """Lightweight geometry summary for a Blender object."""

    name: str
    vertex_count: int
    triangle_count: int
    is_body: bool = False
    is_wheel: bool = False


@dataclass(frozen=True, slots=True)
class VehicleAnalysisReport:
    """Result produced by vehicle structure analysis."""

    blend_file: Path
    has_vehicle_body: bool
    wheel_count: int
    object_count: int
    vertex_count: int
    triangle_count: int
    objects: tuple[VehicleObjectSummary, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_successful(self) -> bool:
        return not self.errors

    @classmethod
    def empty(cls, blend_file: Path) -> "VehicleAnalysisReport":
        return cls(
            blend_file=blend_file,
            has_vehicle_body=False,
            wheel_count=0,
            object_count=0,
            vertex_count=0,
            triangle_count=0,
        )

