from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BoundingBox:
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

    @property
    def size_x(self) -> float:
        return self.max_x - self.min_x

    @property
    def size_y(self) -> float:
        return self.max_y - self.min_y

    @property
    def size_z(self) -> float:
        return self.max_z - self.min_z


@dataclass(frozen=True, slots=True)
class GeometryOverallStats:
    vertices: int
    edges: int
    faces: int
    triangles: int
    bounding_box: BoundingBox


@dataclass(frozen=True, slots=True)
class PlanarRegionStats:
    region_count: int
    face_percentage: float
    triangle_percentage: float


@dataclass(frozen=True, slots=True)
class CurvatureBucket:
    name: str
    triangle_count: int
    percentage: float


@dataclass(frozen=True, slots=True)
class BoundaryStats:
    count: int
    length: float


@dataclass(frozen=True, slots=True)
class DenseRegion:
    region_id: str
    triangle_count: int
    surface_area: float
    density: float


@dataclass(frozen=True, slots=True)
class SilhouetteViewStats:
    name: str
    outline_triangle_count: int


@dataclass(frozen=True, slots=True)
class SilhouetteTriangle:
    object_name: str
    triangle_index: int
    silhouette_hits: int


@dataclass(frozen=True, slots=True)
class SilhouetteRegion:
    region_id: str
    object_name: str
    triangle_count: int
    max_hits: int
    average_hits: float
    recommended_action: str


@dataclass(frozen=True, slots=True)
class SilhouetteStats:
    view_count: int
    total_outline_triangles: int
    protected_triangle_count: int
    protected_triangle_percentage: float
    max_hits: int
    views: tuple[SilhouetteViewStats, ...]
    top_triangles: tuple[SilhouetteTriangle, ...]
    protected_regions: tuple[SilhouetteRegion, ...]


@dataclass(frozen=True, slots=True)
class TriangleDistribution:
    min_area: float
    max_area: float
    median_area: float


@dataclass(frozen=True, slots=True)
class OptimizationCandidate:
    region_id: str
    region_type: str
    recommended_action: str
    triangle_count: int
    surface_area: float
    density: float
    curvature: float
    silhouette_score: float
    confidence: float
    rationale: str


@dataclass(frozen=True, slots=True)
class GeometryReport:
    source_file: Path
    report_json_path: Path
    heatmap_image_path: Path
    overall: GeometryOverallStats
    planar_regions: PlanarRegionStats
    curvature: tuple[CurvatureBucket, ...]
    boundary: BoundaryStats
    dense_regions: tuple[DenseRegion, ...]
    silhouette: SilhouetteStats
    triangle_distribution: TriangleDistribution
    optimization_candidates: tuple[OptimizationCandidate, ...]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def is_successful(self) -> bool:
        return not self.errors
