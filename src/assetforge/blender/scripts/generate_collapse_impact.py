from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from generate_qem_heatmap import (  # noqa: E402
    _add_quadric,
    _apply_cost_visualization,
    _cost_statistics_for_costs,
    _heat_color,
    _import_source,
    _mesh_objects,
    _normal_from_triangle,
    _plane_from_triangle,
    _quadric_from_plane,
    _render_heatmap,
    _sum_quadrics,
    _write_ply,
    _zero_quadric,
)


def _emit_progress(percent: int, stage: str) -> None:
    print(
        "ASSETFORGE_PROGRESS "
        + json.dumps(
            {
                "kind": "collapse_impact",
                "percent": max(0, min(100, int(percent))),
                "stage": stage,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def _area(a: Vector, b: Vector, c: Vector) -> float:
    return 0.5 * (b - a).cross(c - a).length


def _triangle_edges(indices: tuple[int, int, int]) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    a, b, c = indices
    return tuple(sorted((a, b))), tuple(sorted((b, c))), tuple(sorted((c, a)))


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def _quadric_error(quadric: list[list[float]], position: Vector) -> float:
    vector = (float(position.x), float(position.y), float(position.z), 1.0)
    total = 0.0
    for row in range(4):
        for col in range(4):
            total += vector[row] * quadric[row][col] * vector[col]
    return max(0.0, float(total))


def _segment_minimum_qem_position(quadric: list[list[float]], v0: Vector, v1: Vector) -> Vector:
    direction = v1 - v0
    homogeneous_origin = (float(v0.x), float(v0.y), float(v0.z), 1.0)
    homogeneous_direction = (float(direction.x), float(direction.y), float(direction.z), 0.0)
    denominator = 0.0
    numerator = 0.0
    for row in range(4):
        for col in range(4):
            denominator += homogeneous_direction[row] * quadric[row][col] * homogeneous_direction[col]
            numerator += homogeneous_direction[row] * quadric[row][col] * homogeneous_origin[col]
    t = 0.5 if abs(denominator) <= 1e-12 else -numerator / denominator
    return v0 + direction * max(0.0, min(1.0, float(t)))


def _point_lies_on_segment(point: Vector, v0: Vector, v1: Vector) -> bool:
    edge = v1 - v0
    edge_length_squared = edge.length_squared
    if edge_length_squared <= 1e-24:
        return False
    relative = point - v0
    t = relative.dot(edge) / edge_length_squared
    if t < -1e-6 or t > 1.0 + 1e-6:
        return False
    projection = v0 + edge * t
    edge_length = math.sqrt(edge_length_squared)
    return (point - projection).length <= max(edge_length * 1e-5, 1e-8)


def _constrained_qem_position(quadric: list[list[float]], v0: Vector, v1: Vector) -> tuple[Vector, str]:
    midpoint = (v0 + v1) * 0.5
    segment_position = _segment_minimum_qem_position(quadric, v0, v1)
    candidates: list[tuple[str, Vector]] = [
        ("v0", v0.copy()),
        ("v1", v1.copy()),
        ("midpoint", midpoint),
        ("segment", segment_position),
    ]

    matrix = (
        (quadric[0][0], quadric[0][1], quadric[0][2]),
        (quadric[1][0], quadric[1][1], quadric[1][2]),
        (quadric[2][0], quadric[2][1], quadric[2][2]),
    )
    rhs = (-quadric[0][3], -quadric[1][3], -quadric[2][3])
    solved = _solve_3x3(matrix, rhs)
    if solved is not None and _point_lies_on_segment(solved, v0, v1):
        candidates.append(("optimal_segment", solved))
    name, position = min(candidates, key=lambda item: _quadric_error(quadric, item[1]))
    return position, name


def _solve_3x3(matrix: tuple[tuple[float, float, float], ...], rhs: tuple[float, float, float]) -> Vector | None:
    determinant = _det3(matrix)
    if abs(determinant) <= 1e-12:
        return None
    mx = (
        (rhs[0], matrix[0][1], matrix[0][2]),
        (rhs[1], matrix[1][1], matrix[1][2]),
        (rhs[2], matrix[2][1], matrix[2][2]),
    )
    my = (
        (matrix[0][0], rhs[0], matrix[0][2]),
        (matrix[1][0], rhs[1], matrix[1][2]),
        (matrix[2][0], rhs[2], matrix[2][2]),
    )
    mz = (
        (matrix[0][0], matrix[0][1], rhs[0]),
        (matrix[1][0], matrix[1][1], rhs[1]),
        (matrix[2][0], matrix[2][1], rhs[2]),
    )
    return Vector((_det3(mx) / determinant, _det3(my) / determinant, _det3(mz) / determinant))


def _det3(matrix: tuple[tuple[float, float, float], ...]) -> float:
    return (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )


def _new_position(
    vertex_index: int,
    v0: int,
    v1: int,
    placement: Vector,
    positions: list[Vector],
) -> Vector:
    return placement if vertex_index in {v0, v1} else positions[vertex_index]


def _local_edge_lengths(
    face_indices: set[int],
    triangles: list[tuple[int, int, int]],
    positions: list[Vector],
) -> list[float]:
    lengths: list[float] = []
    for face_index in face_indices:
        triangle = triangles[face_index]
        for first, second in _triangle_edges(triangle):
            lengths.append((positions[first] - positions[second]).length)
    return lengths


def _impact_for_edge(
    edge: tuple[int, int],
    placement: Vector,
    triangles: list[tuple[int, int, int]],
    positions: list[Vector],
    vertex_faces: dict[int, set[int]],
) -> dict[str, float]:
    v0, v1 = edge
    affected_faces = set(vertex_faces.get(v0, set()))
    affected_faces.update(vertex_faces.get(v1, set()))
    local_median_edge = max(_median(_local_edge_lengths(affected_faces, triangles, positions)), 1e-12)
    normal_deltas: list[float] = []
    area_deltas: list[float] = []
    edge_distortions: list[float] = []
    removed_faces = 0

    for face_index in affected_faces:
        triangle = triangles[face_index]
        if v0 in triangle and v1 in triangle:
            removed_faces += 1
            continue
        before = [positions[index] for index in triangle]
        after = [_new_position(index, v0, v1, placement, positions) for index in triangle]
        before_normal = _normal_from_triangle(before[0], before[1], before[2])
        after_normal = _normal_from_triangle(after[0], after[1], after[2])
        if before_normal is None or after_normal is None:
            normal_deltas.append(1.0)
        else:
            dot = max(-1.0, min(1.0, before_normal.dot(after_normal)))
            normal_deltas.append(math.acos(dot) / math.pi)

        before_area = max(_area(before[0], before[1], before[2]), 1e-12)
        after_area = max(_area(after[0], after[1], after[2]), 1e-12)
        area_deltas.append(abs(math.log(after_area / before_area)))

        for first_index, second_index in ((0, 1), (1, 2), (2, 0)):
            if triangle[first_index] not in {v0, v1} and triangle[second_index] not in {v0, v1}:
                continue
            new_length = max((after[first_index] - after[second_index]).length, 1e-12)
            edge_distortions.append(abs(math.log(new_length / local_median_edge)))

    normal_impact = statistics.fmean(normal_deltas) if normal_deltas else 0.0
    area_impact = statistics.fmean(area_deltas) if area_deltas else 0.0
    edge_length_impact = statistics.fmean(edge_distortions) if edge_distortions else 0.0
    removed_ratio = removed_faces / max(len(affected_faces), 1)
    combined_experimental_impact = (
        normal_impact
        + min(area_impact, 2.0) * 0.35
        + min(edge_length_impact, 2.0) * 0.25
    )
    return {
        "normal_impact": normal_impact,
        "area_impact": area_impact,
        "edge_length_impact": edge_length_impact,
        "removed_face_ratio": removed_ratio,
        "combined_experimental_impact": combined_experimental_impact,
        "affected_face_count": float(len(affected_faces)),
        "removed_face_count": float(removed_faces),
    }


def _collect_collapse_impact_data(mesh_objects: list[bpy.types.Object]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    total_vertices = 0
    total_triangles = 0
    fallback_edges = 0

    for obj in mesh_objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        positions = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
        triangles = [tuple(int(index) for index in triangle.vertices) for triangle in mesh.loop_triangles]
        total_vertices += len(positions)
        total_triangles += len(triangles)
        vertex_quadrics = [_zero_quadric() for _ in positions]
        vertex_faces: dict[int, set[int]] = {}
        edge_to_faces: dict[tuple[int, int], set[int]] = {}

        for face_index, triangle in enumerate(triangles):
            a, b, c = (positions[index] for index in triangle)
            plane = _plane_from_triangle(a, b, c)
            if plane is not None:
                face_quadric = _quadric_from_plane(plane)
                for vertex_index in triangle:
                    _add_quadric(vertex_quadrics[vertex_index], face_quadric)
            for vertex_index in triangle:
                vertex_faces.setdefault(vertex_index, set()).add(face_index)
            for edge in _triangle_edges(triangle):
                edge_to_faces.setdefault(edge, set()).add(face_index)

        for local_edge_index, edge in enumerate(sorted(edge_to_faces)):
            v0_index, v1_index = edge
            q_edge = _sum_quadrics(vertex_quadrics[v0_index], vertex_quadrics[v1_index])
            placement, placement_source = _constrained_qem_position(q_edge, positions[v0_index], positions[v1_index])
            if placement_source not in {"optimal_segment", "segment"}:
                fallback_edges += 1
            impact = _impact_for_edge(edge, placement, triangles, positions, vertex_faces)
            edges.append(
                {
                    "object_name": obj.name,
                    "edge_id": len(edges),
                    "local_edge_id": local_edge_index,
                    "v0": int(v0_index),
                    "v1": int(v1_index),
                    "global_v0": f"{obj.name}:{v0_index}",
                    "global_v1": f"{obj.name}:{v1_index}",
                    "v0_position": [float(positions[v0_index].x), float(positions[v0_index].y), float(positions[v0_index].z)],
                    "v1_position": [float(positions[v1_index].x), float(positions[v1_index].y), float(positions[v1_index].z)],
                    "optimal_position": [float(placement.x), float(placement.y), float(placement.z)],
                    "placement_source": placement_source,
                    "is_boundary": len(edge_to_faces[edge]) == 1,
                    **impact,
                }
            )

    return edges, {
        "vertex_count": total_vertices,
        "triangle_count": total_triangles,
        "edge_count": len(edges),
        "placement_fallback_edges": fallback_edges,
    }


def _stats(edges: list[dict[str, Any]], key: str) -> dict[str, float]:
    values = [float(edge[key]) for edge in edges]
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "median": 0.0, "p75": 0.0, "p90": 0.0, "p99": 0.0}
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p75": _percentile(values, 0.75),
        "p90": _percentile(values, 0.90),
        "p99": _percentile(values, 0.99),
    }


def _edge_summary(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "edge_id": edge["edge_id"],
        "object_name": edge["object_name"],
        "v0": edge["v0"],
        "v1": edge["v1"],
        "normal_impact": edge["normal_impact"],
        "area_impact": edge["area_impact"],
        "edge_length_impact": edge["edge_length_impact"],
        "removed_face_ratio": edge["removed_face_ratio"],
        "combined_experimental_impact": edge["combined_experimental_impact"],
        "affected_face_count": int(edge["affected_face_count"]),
        "removed_face_count": int(edge["removed_face_count"]),
        "placement_source": edge["placement_source"],
        "normal_display_heat": edge["normal_impact_display_heat"],
        "is_boundary": edge["is_boundary"],
    }


def _render_metric_heatmap(
    edges: list[dict[str, Any]],
    output_directory: Path,
    metric_key: str,
    file_stem: str,
) -> dict[str, Any]:
    heat_key = f"{metric_key}_heat"
    display_heat_key = f"{metric_key}_display_heat"
    color_key = f"{metric_key}_color_rgb"
    stats = _apply_cost_visualization(edges, metric_key, heat_key, display_heat_key, color_key)
    ply_path = output_directory / f"{file_stem}.ply"
    png_path = output_directory / f"{file_stem}.png"
    inverse_png_path = output_directory / f"{file_stem}_inverse.png"
    _write_ply(edges, ply_path, color_key)
    _render_heatmap(edges, png_path, display_heat_key)
    _render_heatmap(edges, inverse_png_path, display_heat_key, invert=True)
    return {
        "metric": metric_key,
        "ply": str(ply_path),
        "png": str(png_path),
        "inverse_png": str(inverse_png_path),
        "statistics": _stats(edges, metric_key),
        "display_max": stats["display_max"],
        "normalization": {
            "display_heat": "percentile_rank",
            "raw_heat": "min_max",
        },
    }


def generate(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source_file).resolve()
    output_directory = Path(args.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)

    _emit_progress(5, "Importing source model")
    _import_source(source)
    mesh_objects = _mesh_objects()
    _emit_progress(25, "Simulating per-edge collapse impact")
    edges, metadata = _collect_collapse_impact_data(mesh_objects)
    _emit_progress(55, "Rendering normal impact heatmap")
    normal_heatmap = _render_metric_heatmap(edges, output_directory, "normal_impact", "collapse_normal_impact_heatmap")
    _emit_progress(68, "Rendering area impact debug heatmap")
    area_heatmap = _render_metric_heatmap(edges, output_directory, "area_impact", "collapse_area_impact_debug_heatmap")
    _emit_progress(78, "Rendering edge length impact debug heatmap")
    edge_length_heatmap = _render_metric_heatmap(
        edges,
        output_directory,
        "edge_length_impact",
        "collapse_edge_length_impact_debug_heatmap",
    )
    _emit_progress(88, "Rendering removed face ratio debug heatmap")
    removed_face_heatmap = _render_metric_heatmap(
        edges,
        output_directory,
        "removed_face_ratio",
        "collapse_removed_face_ratio_debug_heatmap",
    )

    _apply_cost_visualization(
        edges,
        "combined_experimental_impact",
        "combined_experimental_heat",
        "combined_experimental_display_heat",
        "combined_experimental_color_rgb",
    )

    sorted_edges = sorted(edges, key=lambda edge: float(edge["normal_impact"]))
    report = {
        "source_file": str(source),
        "output_directory": str(output_directory),
        "report_json_path": str(output_directory / "collapse_impact_report.json"),
        "vertex_count": metadata["vertex_count"],
        "triangle_count": metadata["triangle_count"],
        "edge_count": metadata["edge_count"],
        "placement_fallback_edges": metadata["placement_fallback_edges"],
        "default_metric": "normal_impact",
        "metrics": {
            "normal_impact": {
                "role": "default",
                "formula": "mean normal angle change over affected faces that still exist after collapse, normalized by pi",
                **normal_heatmap,
            },
            "area_impact": {
                "role": "debug",
                "formula": "mean abs(log(after_area/before_area)) over affected faces that still exist after collapse",
                **area_heatmap,
            },
            "edge_length_impact": {
                "role": "debug",
                "formula": "mean abs(log(after_edge_length/local_median_edge_length)) over affected edges incident to collapsed vertices",
                **edge_length_heatmap,
            },
            "removed_face_ratio": {
                "role": "debug",
                "formula": "faces removed by this collapse divided by all affected faces",
                **removed_face_heatmap,
            },
            "combined_experimental_impact": {
                "role": "experimental_hidden",
                "formula": "normal_impact + 0.35*clamp(area_impact,0,2) + 0.25*clamp(edge_length_impact,0,2)",
                "statistics": _stats(edges, "combined_experimental_impact"),
                "note": "Not rendered as the default heatmap and not intended as an executor cost yet.",
            },
        },
        "visualization": {
            "display_heat_normalization": "percentile_rank",
            "raw_heat_normalization": "min_max",
            "default_display_max_impact": normal_heatmap["display_max"],
            "color_scale": "blue_cyan_green_yellow_red",
            "red_meaning": "higher normal_impact in the default map",
        },
        "top_50_highest_normal_impact_edges": [_edge_summary(edge) for edge in reversed(sorted_edges[-50:])],
        "top_50_lowest_normal_impact_edges": [_edge_summary(edge) for edge in sorted_edges[:50]],
        "heatmap_ply": normal_heatmap["ply"],
        "heatmap_png": normal_heatmap["png"],
        "heatmap_inverse_png": normal_heatmap["inverse_png"],
        "normal_impact_heatmap_ply": normal_heatmap["ply"],
        "normal_impact_heatmap_png": normal_heatmap["png"],
        "normal_impact_heatmap_inverse_png": normal_heatmap["inverse_png"],
        "area_impact_debug_heatmap_ply": area_heatmap["ply"],
        "area_impact_debug_heatmap_png": area_heatmap["png"],
        "area_impact_debug_heatmap_inverse_png": area_heatmap["inverse_png"],
        "edge_length_impact_debug_heatmap_ply": edge_length_heatmap["ply"],
        "edge_length_impact_debug_heatmap_png": edge_length_heatmap["png"],
        "edge_length_impact_debug_heatmap_inverse_png": edge_length_heatmap["inverse_png"],
        "removed_face_ratio_debug_heatmap_ply": removed_face_heatmap["ply"],
        "removed_face_ratio_debug_heatmap_png": removed_face_heatmap["png"],
        "removed_face_ratio_debug_heatmap_inverse_png": removed_face_heatmap["inverse_png"],
        "observations": [
            "This is a diagnostic only; it simulates one edge collapse at a time and does not modify the mesh.",
            "The default map shows normal_impact only; faces deleted by the collapse are excluded from normal and area comparisons.",
            "Area, edge-length, and removed-face maps are debug views and are not part of the default signal.",
            "Combined impact is experimental and hidden from default display until the metric is validated.",
        ],
        "errors": [],
    }
    Path(report["report_json_path"]).write_text(json.dumps(report, indent=2), encoding="utf-8")
    _emit_progress(100, "Collapse impact heatmap complete")
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a collapse-impact diagnostic heatmap.")
    parser.add_argument("--source-file", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    report = generate(args)
    Path(args.output_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]))
