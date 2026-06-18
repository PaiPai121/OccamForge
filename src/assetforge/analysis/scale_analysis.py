from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Sequence


Vector3 = tuple[float, float, float]
Triangle = tuple[int, int, int]


@dataclass(frozen=True)
class ScaleAnalysisMesh:
    vertices: Sequence[Vector3]
    triangles: Sequence[Triangle]
    object_name: str = "mesh"


@dataclass(frozen=True)
class ScaleAnalysisResult:
    object_name: str
    vertex_count: int
    triangle_count: int
    bbox_diagonal: float
    scales: list[float]
    mean_curvature: list[float]
    scale_responses: list[list[float]]
    center_surround_response: list[float]
    scale_thresholds: list[float]
    scale_persistence: list[float]
    tiny_detail_score: list[float]
    errors: list[str]


def analyze_scale_persistence(
    mesh: ScaleAnalysisMesh,
    scales: Sequence[float] | None = None,
) -> ScaleAnalysisResult:
    """Compute a V0 multi-scale persistence signal for a single triangle mesh.

    V0 intentionally favors explainability over speed. Neighborhoods are found by
    direct distance checks so the same implementation can run in ordinary tests and
    inside Blender without optional dependencies.
    """

    vertices = [tuple(map(float, vertex)) for vertex in mesh.vertices]
    triangles = [_valid_triangle(triangle, len(vertices)) for triangle in mesh.triangles]
    triangles = [triangle for triangle in triangles if triangle is not None]
    errors: list[str] = []

    bbox_diagonal = _bbox_diagonal(vertices)
    default_scales = _default_scales(bbox_diagonal)
    scale_values = [float(scale) for scale in (scales or default_scales) if float(scale) > 0.0]
    if len(scale_values) < 2 and bbox_diagonal > 0.0:
        scale_values = default_scales

    vertex_count = len(vertices)
    if vertex_count == 0:
        errors.append("Mesh has no vertices.")
        return _empty_result(mesh.object_name, 0, len(triangles), bbox_diagonal, scale_values, errors)
    if not triangles:
        errors.append("Mesh has no valid triangles.")
        return _empty_result(
            mesh.object_name,
            vertex_count,
            0,
            bbox_diagonal,
            scale_values,
            errors,
        )
    if bbox_diagonal <= 1e-12:
        errors.append("Mesh bbox diagonal is zero.")
        return _empty_result(
            mesh.object_name,
            vertex_count,
            len(triangles),
            bbox_diagonal,
            scale_values,
            errors,
        )

    # V0 uses adjacent face-normal variation as the discrete curvature proxy H.
    # This is a per-vertex scale-analysis signal, not a QEM edge-collapse cost.
    mean_curvature = _normal_variation(vertices, triangles)
    scale_fields = [_radius_average(vertices, mean_curvature, radius) for radius in scale_values]
    responses: list[list[float]] = []
    for index in range(len(scale_fields) - 1):
        responses.append(
            [
                # Center-surround response: S(v,sigma)=|G(H,sigma)-G(H,2sigma)|.
                abs(scale_fields[index][vertex_index] - scale_fields[index + 1][vertex_index])
                for vertex_index in range(vertex_count)
            ]
        )

    thresholds = [_percentile(response, 75.0) for response in responses]
    persistence_raw = [0.0 for _ in vertices]
    for response, threshold in zip(responses, thresholds, strict=False):
        for vertex_index, value in enumerate(response):
            if value > threshold and value > 1e-12:
                persistence_raw[vertex_index] += 1.0

    max_persistence = max(float(len(responses)), 1.0)
    scale_persistence = [value / max_persistence for value in persistence_raw]
    center_surround_response = _center_surround_scores(responses)
    tiny_detail_score = _tiny_detail_scores(responses, thresholds)

    return ScaleAnalysisResult(
        object_name=mesh.object_name,
        vertex_count=vertex_count,
        triangle_count=len(triangles),
        bbox_diagonal=bbox_diagonal,
        scales=scale_values,
        mean_curvature=_normalize(mean_curvature),
        scale_responses=[_normalize(response) for response in responses],
        center_surround_response=center_surround_response,
        scale_thresholds=thresholds,
        scale_persistence=scale_persistence,
        tiny_detail_score=tiny_detail_score,
        errors=errors,
    )


def scale_analysis_report_dict(
    result: ScaleAnalysisResult,
    input_path: str,
    output_directory: str,
    persistence_heatmap: str,
    tiny_detail_heatmap: str,
    mean_curvature_heatmap: str = "",
    center_surround_heatmap: str = "",
) -> dict[str, object]:
    mean_curvature_stats = _stats(result.mean_curvature)
    center_surround_stats = _stats(result.center_surround_response)
    persistence_stats = _stats(result.scale_persistence)
    tiny_stats = _stats(result.tiny_detail_score)
    low_persistence_ratio = _ratio_below(result.scale_persistence, 0.25)
    high_persistence_ratio = _ratio_above(result.scale_persistence, 0.75)
    tiny_detail_ratio = _ratio_above(result.tiny_detail_score, 0.60)
    return {
        "input": input_path,
        "object_name": result.object_name,
        "output_directory": output_directory,
        "vertex_count": result.vertex_count,
        "triangle_count": result.triangle_count,
        "bbox_diagonal": result.bbox_diagonal,
        "scales": result.scales,
        "mean_curvature_stats": mean_curvature_stats,
        "center_surround_stats": center_surround_stats,
        "persistence_stats": persistence_stats,
        "tiny_detail_stats": tiny_stats,
        "center_surround_formula": "S(v,sigma)=abs(G(H,sigma)-G(H,2sigma)); V0 H is per-vertex adjacent face-normal variation, not QEM edge cost",
        "interpretation": {
            "low_persistence_ratio": low_persistence_ratio,
            "high_persistence_ratio": high_persistence_ratio,
            "tiny_detail_ratio": tiny_detail_ratio,
        },
        "scale_thresholds": result.scale_thresholds,
        "mean_curvature_heatmap": mean_curvature_heatmap,
        "center_surround_heatmap": center_surround_heatmap,
        "scale_persistence_heatmap": persistence_heatmap,
        "tiny_detail_heatmap": tiny_detail_heatmap,
        "errors": result.errors,
    }


def _empty_result(
    object_name: str,
    vertex_count: int,
    triangle_count: int,
    bbox_diagonal: float,
    scales: Sequence[float],
    errors: list[str],
) -> ScaleAnalysisResult:
    zeros = [0.0 for _ in range(vertex_count)]
    return ScaleAnalysisResult(
        object_name=object_name,
        vertex_count=vertex_count,
        triangle_count=triangle_count,
        bbox_diagonal=bbox_diagonal,
        scales=list(scales),
        mean_curvature=zeros,
        scale_responses=[],
        center_surround_response=zeros,
        scale_thresholds=[],
        scale_persistence=zeros,
        tiny_detail_score=zeros,
        errors=errors,
    )


def _valid_triangle(triangle: Sequence[int], vertex_count: int) -> Triangle | None:
    if len(triangle) != 3:
        return None
    a, b, c = int(triangle[0]), int(triangle[1]), int(triangle[2])
    if a == b or b == c or a == c:
        return None
    if min(a, b, c) < 0 or max(a, b, c) >= vertex_count:
        return None
    return a, b, c


def _default_scales(diagonal: float) -> list[float]:
    if diagonal <= 0.0:
        return []
    return [diagonal * factor for factor in (0.005, 0.01, 0.02, 0.04, 0.08)]


def _bbox_diagonal(vertices: Sequence[Vector3]) -> float:
    if not vertices:
        return 0.0
    mins = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
    maxs = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
    return _length((maxs[0] - mins[0], maxs[1] - mins[1], maxs[2] - mins[2]))


def _normal_variation(vertices: Sequence[Vector3], triangles: Sequence[Triangle]) -> list[float]:
    face_normals: list[Vector3 | None] = []
    vertex_faces: list[list[int]] = [[] for _ in vertices]
    for face_index, (a, b, c) in enumerate(triangles):
        normal = _triangle_normal(vertices[a], vertices[b], vertices[c])
        face_normals.append(normal)
        if normal is None:
            continue
        vertex_faces[a].append(face_index)
        vertex_faces[b].append(face_index)
        vertex_faces[c].append(face_index)

    variations: list[float] = []
    for faces in vertex_faces:
        normals = [face_normals[index] for index in faces if face_normals[index] is not None]
        if len(normals) < 2:
            variations.append(0.0)
            continue
        average = _normalize_vector(
            (
                sum(normal[0] for normal in normals),
                sum(normal[1] for normal in normals),
                sum(normal[2] for normal in normals),
            )
        )
        if average is None:
            variations.append(0.0)
            continue
        angles = [_angle_between(average, normal) for normal in normals]
        variations.append(sum(angles) / len(angles) / math.pi)
    return variations


def _radius_average(
    vertices: Sequence[Vector3],
    values: Sequence[float],
    radius: float,
) -> list[float]:
    if not vertices:
        return []
    if len(vertices) <= 512:
        return _radius_average_direct(vertices, values, radius)

    cell_size = max(radius, 1e-12)
    grid: dict[tuple[int, int, int], list[int]] = {}
    for index, vertex in enumerate(vertices):
        grid.setdefault(_grid_cell(vertex, cell_size), []).append(index)

    radius_squared = radius * radius
    averaged: list[float] = []
    for center in vertices:
        cell = _grid_cell(center, cell_size)
        total = 0.0
        count = 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for index in grid.get((cell[0] + dx, cell[1] + dy, cell[2] + dz), []):
                        if _distance_squared(center, vertices[index]) <= radius_squared:
                            total += values[index]
                            count += 1
        averaged.append(total / count if count else 0.0)
    return averaged


def _radius_average_direct(
    vertices: Sequence[Vector3],
    values: Sequence[float],
    radius: float,
) -> list[float]:
    radius_squared = radius * radius
    averaged: list[float] = []
    for center in vertices:
        total = 0.0
        count = 0
        for vertex, value in zip(vertices, values, strict=False):
            if _distance_squared(center, vertex) <= radius_squared:
                total += value
                count += 1
        averaged.append(total / count if count else 0.0)
    return averaged


def _grid_cell(vertex: Vector3, cell_size: float) -> tuple[int, int, int]:
    return (
        math.floor(vertex[0] / cell_size),
        math.floor(vertex[1] / cell_size),
        math.floor(vertex[2] / cell_size),
    )


def _tiny_detail_scores(responses: Sequence[Sequence[float]], thresholds: Sequence[float]) -> list[float]:
    if not responses:
        return []
    vertex_count = len(responses[0])
    scores: list[float] = []
    for vertex_index in range(vertex_count):
        first_threshold = max(thresholds[0], 1e-12)
        first_strength = max(0.0, responses[0][vertex_index] - thresholds[0]) / first_threshold
        later_hits = 0
        later_strength = 0.0
        for response, threshold in zip(responses[1:], thresholds[1:], strict=False):
            if response[vertex_index] > threshold and response[vertex_index] > 1e-12:
                later_hits += 1
            later_strength += response[vertex_index] / max(threshold, 1e-12)
        later_count = max(len(responses) - 1, 1)
        isolation = max(0.0, 1.0 - (later_hits / later_count) * 0.8 - (later_strength / later_count) * 0.2)
        scores.append(min(1.0, first_strength) * isolation)
    return _normalize(scores)


def _center_surround_scores(responses: Sequence[Sequence[float]]) -> list[float]:
    if not responses:
        return []
    vertex_count = len(responses[0])
    scores = [
        max(response[vertex_index] for response in responses)
        for vertex_index in range(vertex_count)
    ]
    return _normalize(scores)


def _stats(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0}
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "p25": _percentile(values, 25.0),
        "p50": _percentile(values, 50.0),
        "p75": _percentile(values, 75.0),
    }


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _normalize(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high - low <= 1e-12:
        return [0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def _ratio_below(values: Sequence[float], threshold: float) -> float:
    return sum(1 for value in values if value <= threshold) / len(values) if values else 0.0


def _ratio_above(values: Sequence[float], threshold: float) -> float:
    return sum(1 for value in values if value >= threshold) / len(values) if values else 0.0


def _triangle_normal(a: Vector3, b: Vector3, c: Vector3) -> Vector3 | None:
    normal = _cross(_sub(b, a), _sub(c, a))
    return _normalize_vector(normal)


def _angle_between(a: Vector3, b: Vector3) -> float:
    dot = max(-1.0, min(1.0, _dot(a, b)))
    return math.acos(dot)


def _normalize_vector(vector: Vector3) -> Vector3 | None:
    length = _length(vector)
    if length <= 1e-12:
        return None
    return vector[0] / length, vector[1] / length, vector[2] / length


def _sub(a: Vector3, b: Vector3) -> Vector3:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(vector: Vector3) -> float:
    return math.sqrt(_dot(vector, vector))


def _distance_squared(a: Vector3, b: Vector3) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    return dx * dx + dy * dy + dz * dz
