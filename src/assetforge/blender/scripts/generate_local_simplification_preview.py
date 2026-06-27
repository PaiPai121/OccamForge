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
for parent in Path(__file__).resolve().parents:
    if (parent / "assetforge").is_dir():
        sys.path.insert(0, str(parent))
        break

from assetforge.analysis.edge_collapse import (  # noqa: E402
    CollapseExecutor,
    EdgeCollapseMesh,
    QEMPlacement,
    SelectedAFCostProvider,
    _optimal_qem_position,
    _quadric_error,
    _sum_quadrics,
    _vertex_quadrics,
)
from assetforge.analysis.scale_analysis import ScaleAnalysisMesh, analyze_scale_persistence  # noqa: E402
from generate_afcost_candidates import (  # noqa: E402
    CANDIDATE_DEFINITIONS,
    _candidate_values,
    _qem_base_values,
    _stats,
)
from generate_model_preview import generate as generate_model_preview  # noqa: E402
from analyze_vehicle import _write_preview_obj  # noqa: E402
from optimize_vehicle import _count_scene_triangles, _mesh_objects  # noqa: E402


def _emit_progress(payload: dict[str, Any]) -> None:
    print("ASSETFORGE_PROGRESS " + json.dumps(payload, separators=(",", ":")), flush=True)


def _valid_triangle(triangle: tuple[int, int, int], vertex_count: int) -> tuple[int, int, int] | None:
    a, b, c = triangle
    if a == b or b == c or a == c:
        return None
    if min(a, b, c) < 0 or max(a, b, c) >= vertex_count:
        return None
    return a, b, c


def _object_mesh(obj: bpy.types.Object) -> EdgeCollapseMesh:
    mesh = obj.data
    mesh.calc_loop_triangles()
    vertices = [
        (float(vertex.co.x), float(vertex.co.y), float(vertex.co.z))
        for vertex in mesh.vertices
    ]
    triangles: list[tuple[int, int, int]] = []
    for triangle in mesh.loop_triangles:
        candidate = tuple(int(index) for index in triangle.vertices)
        valid = _valid_triangle(candidate, len(vertices))
        if valid is not None:
            triangles.append(valid)
    return EdgeCollapseMesh(vertices=vertices, triangles=triangles, object_name=str(obj.name))


def _edge_set(triangles: list[tuple[int, int, int]]) -> list[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    for a, b, c in triangles:
        for first, second in ((a, b), (b, c), (c, a)):
            edges.add((first, second) if first < second else (second, first))
    return sorted(edges)


def _choose_candidate(candidate_values: dict[str, list[float]], requested: str) -> str:
    if requested != "auto":
        if requested not in candidate_values:
            available = ", ".join(sorted(candidate_values))
            raise ValueError(f"Unknown combo candidate {requested!r}. Available: {available}")
        return requested
    return min(
        candidate_values,
        key=lambda name: statistics.fmean(candidate_values[name]) if candidate_values[name] else math.inf,
    )


def _combo_scores_for_mesh(
    mesh: EdgeCollapseMesh,
    requested_candidate: str,
    lambda_value: float,
    eps: float,
) -> tuple[str, dict[tuple[int, int], float], dict[str, Any]]:
    edges = _edge_set(list(mesh.triangles))
    if not edges:
        return requested_candidate, {}, {"edge_count": 0, "candidate_stats": {}}

    scale_result = analyze_scale_persistence(
        ScaleAnalysisMesh(
            vertices=mesh.vertices,
            triangles=mesh.triangles,
            object_name=mesh.object_name,
        )
    )
    quadrics = _vertex_quadrics(mesh.vertices, mesh.triangles)
    qem_values = []
    for edge in edges:
        quadric = _sum_quadrics(quadrics[edge[0]], quadrics[edge[1]])
        placement = _optimal_qem_position(quadric, mesh.vertices[edge[0]], mesh.vertices[edge[1]])
        qem_values.append(_quadric_error(quadric, placement))
    persistence_values = [
        max(scale_result.scale_persistence[edge[0]], scale_result.scale_persistence[edge[1]])
        for edge in edges
    ]
    tiny_values = [
        max(scale_result.tiny_detail_score[edge[0]], scale_result.tiny_detail_score[edge[1]])
        for edge in edges
    ]
    all_values = _candidate_values(
        _qem_base_values(qem_values, eps),
        persistence_values,
        tiny_values,
        lambda_value,
        eps,
    )
    selected = _choose_candidate(all_values, requested_candidate)
    scores = {
        edge: float(score)
        for edge, score in zip(edges, all_values[selected], strict=False)
        if math.isfinite(float(score))
    }
    fallback_score = 0.0
    for edge in edges:
        scores.setdefault(edge, fallback_score)
    return selected, scores, {
        "edge_count": len(edges),
        "candidate": selected,
        "candidate_formula": dict(CANDIDATE_DEFINITIONS).get(selected, selected),
        "candidate_stats": _stats(list(scores.values())),
        "scale_errors": scale_result.errors,
    }


def _apply_result_to_object(
    obj: bpy.types.Object,
    vertices: list[tuple[float, float, float]],
    triangles: list[tuple[int, int, int]],
    vertex_sources: list[frozenset[int]],
) -> None:
    old_mesh = obj.data
    old_mesh.calc_loop_triangles()
    source_triangles = [
        tuple(int(vertex) for vertex in triangle.vertices)
        for triangle in old_mesh.loop_triangles
    ]
    source_polygon_indices = [int(triangle.polygon_index) for triangle in old_mesh.loop_triangles]
    vertex_to_source_triangles: dict[int, list[int]] = {}
    exact_source_triangles: dict[tuple[int, int, int], int] = {}
    for index, triangle in enumerate(source_triangles):
        exact_source_triangles[tuple(sorted(triangle))] = index
        for vertex in triangle:
            vertex_to_source_triangles.setdefault(vertex, []).append(index)

    new_mesh = bpy.data.meshes.new(f"{old_mesh.name}_local_simplified")
    new_mesh.from_pydata(vertices, [], triangles)
    new_mesh.update()
    for material in old_mesh.materials:
        new_mesh.materials.append(material)
    _copy_face_materials_and_uvs(
        old_mesh,
        new_mesh,
        triangles,
        source_triangles,
        source_polygon_indices,
        exact_source_triangles,
        vertex_to_source_triangles,
        vertex_sources,
    )
    obj.data = new_mesh
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)


def _copy_face_materials_and_uvs(
    old_mesh: bpy.types.Mesh,
    new_mesh: bpy.types.Mesh,
    triangles: list[tuple[int, int, int]],
    source_triangles: list[tuple[int, int, int]],
    source_polygon_indices: list[int],
    exact_source_triangles: dict[tuple[int, int, int], int],
    vertex_to_source_triangles: dict[int, list[int]],
    vertex_sources: list[frozenset[int]],
) -> None:
    source_triangle_for_polygon: list[int | None] = []
    for polygon_index, triangle in enumerate(triangles):
        source_index = _best_source_triangle(
            triangle,
            vertex_sources,
            polygon_index,
            source_triangles,
            exact_source_triangles,
            vertex_to_source_triangles,
        )
        source_triangle_for_polygon.append(source_index)
        if source_index is None:
            continue
        old_polygon = old_mesh.polygons[source_polygon_indices[source_index]]
        if new_mesh.materials:
            new_mesh.polygons[polygon_index].material_index = min(
                int(old_polygon.material_index),
                len(new_mesh.materials) - 1,
            )

    for old_uv_layer in old_mesh.uv_layers:
        new_uv_layer = new_mesh.uv_layers.new(name=old_uv_layer.name)
        for polygon_index, polygon in enumerate(new_mesh.polygons):
            source_index = source_triangle_for_polygon[polygon_index]
            if source_index is None:
                continue
            old_polygon = old_mesh.polygons[source_polygon_indices[source_index]]
            source_vertices = source_triangles[source_index]
            source_loop_by_vertex = {
                int(vertex): int(loop_index)
                for vertex, loop_index in zip(source_vertices, old_polygon.loop_indices, strict=False)
            }
            fallback_uv = _average_uv(old_uv_layer, old_polygon.loop_indices)
            for vertex, loop_index in zip(polygon.vertices, polygon.loop_indices, strict=False):
                source_loop_index = _direct_source_loop(
                    int(vertex),
                    vertex_sources,
                    source_loop_by_vertex,
                )
                if source_loop_index is None:
                    new_uv_layer.data[loop_index].uv = _interpolated_uv(
                        old_mesh,
                        old_uv_layer,
                        old_polygon,
                        source_vertices,
                        new_mesh.vertices[int(vertex)].co,
                        fallback_uv,
                    )
                else:
                    new_uv_layer.data[loop_index].uv = old_uv_layer.data[source_loop_index].uv


def _best_source_triangle(
    triangle: tuple[int, int, int],
    vertex_sources: list[frozenset[int]],
    polygon_index: int,
    source_triangles: list[tuple[int, int, int]],
    exact_source_triangles: dict[tuple[int, int, int], int],
    vertex_to_source_triangles: dict[int, list[int]],
) -> int | None:
    exact = exact_source_triangles.get(tuple(sorted(_representative_sources(triangle, vertex_sources))))
    if exact is not None:
        return exact

    candidate_indices: set[int] = set()
    source_vertices = set().union(*(_safe_vertex_sources(vertex_sources, vertex) for vertex in triangle))
    for vertex in source_vertices:
        candidate_indices.update(vertex_to_source_triangles.get(vertex, []))
    if not candidate_indices:
        return polygon_index if polygon_index < len(source_triangles) else None

    return max(
        candidate_indices,
        key=lambda index: (
            len(source_vertices & set(source_triangles[index])),
            -abs(index - polygon_index),
        ),
    )


def _safe_vertex_sources(vertex_sources: list[frozenset[int]], vertex: int) -> frozenset[int]:
    if 0 <= vertex < len(vertex_sources) and vertex_sources[vertex]:
        return vertex_sources[vertex]
    return frozenset({vertex})


def _representative_sources(
    triangle: tuple[int, int, int],
    vertex_sources: list[frozenset[int]],
) -> tuple[int, int, int]:
    representatives = []
    for vertex in triangle:
        sources = _safe_vertex_sources(vertex_sources, vertex)
        representatives.append(min(sources, key=lambda source: abs(source - vertex)))
    return representatives[0], representatives[1], representatives[2]


def _direct_source_loop(
    vertex: int,
    vertex_sources: list[frozenset[int]],
    source_loop_by_vertex: dict[int, int],
) -> int | None:
    for source_vertex in _safe_vertex_sources(vertex_sources, vertex):
        loop_index = source_loop_by_vertex.get(int(source_vertex))
        if loop_index is not None:
            return loop_index
    return None


def _average_uv(old_uv_layer: bpy.types.MeshUVLoopLayer, loop_indices: list[int]) -> Any:
    if not loop_indices:
        return (0.0, 0.0)
    total_u = 0.0
    total_v = 0.0
    for loop_index in loop_indices:
        uv = old_uv_layer.data[int(loop_index)].uv
        total_u += float(uv.x)
        total_v += float(uv.y)
    count = float(len(loop_indices))
    return (total_u / count, total_v / count)


def _interpolated_uv(
    old_mesh: bpy.types.Mesh,
    old_uv_layer: bpy.types.MeshUVLoopLayer,
    old_polygon: bpy.types.MeshPolygon,
    source_vertices: tuple[int, int, int],
    position: Vector,
    fallback_uv: Any,
) -> Any:
    if len(source_vertices) != 3 or len(old_polygon.loop_indices) != 3:
        return fallback_uv
    a = old_mesh.vertices[int(source_vertices[0])].co
    b = old_mesh.vertices[int(source_vertices[1])].co
    c = old_mesh.vertices[int(source_vertices[2])].co
    barycentric = _barycentric_coordinates(position, a, b, c)
    if barycentric is None:
        return fallback_uv
    uvs = [old_uv_layer.data[int(loop_index)].uv for loop_index in old_polygon.loop_indices]
    return (
        float(uvs[0].x) * barycentric[0]
        + float(uvs[1].x) * barycentric[1]
        + float(uvs[2].x) * barycentric[2],
        float(uvs[0].y) * barycentric[0]
        + float(uvs[1].y) * barycentric[1]
        + float(uvs[2].y) * barycentric[2],
    )


def _barycentric_coordinates(
    point: Vector,
    a: Vector,
    b: Vector,
    c: Vector,
) -> tuple[float, float, float] | None:
    v0 = b - a
    v1 = c - a
    v2 = point - a
    d00 = v0.dot(v0)
    d01 = v0.dot(v1)
    d11 = v1.dot(v1)
    d20 = v2.dot(v0)
    d21 = v2.dot(v1)
    denominator = d00 * d11 - d01 * d01
    if abs(denominator) <= 1e-12:
        return None
    v = (d11 * d20 - d01 * d21) / denominator
    w = (d00 * d21 - d01 * d20) / denominator
    u = 1.0 - v - w
    return (
        max(-0.25, min(1.25, float(u))),
        max(-0.25, min(1.25, float(v))),
        max(-0.25, min(1.25, float(w))),
    )


def _score(target_triangles: int, warning_triangles: int, critical_triangles: int) -> int:
    if target_triangles <= warning_triangles:
        return 95
    if target_triangles >= critical_triangles:
        return 35
    span = max(critical_triangles - warning_triangles, 1)
    over = target_triangles - warning_triangles
    return max(35, min(95, int(round(95 - (over / span) * 60))))


def _filename_slug(value: str) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in value)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "auto"


def _rating(score: int) -> str:
    if score < 50:
        return "High Risk"
    if score < 75:
        return "Needs Review"
    if score < 90:
        return "Good"
    return "Excellent"


def generate(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.blend_file).resolve()
    output_directory = Path(args.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    errors: list[str] = []

    if not source.exists():
        return {
            "source_blend_file": str(source),
            "output_directory": str(output_directory),
            "original_triangle_count": 0,
            "profile_id": args.profile_id,
            "items": [],
            "warnings": warnings,
            "errors": [f"Blend file does not exist: {source}"],
        }

    bpy.ops.wm.open_mainfile(filepath=str(source))
    mesh_objects = _mesh_objects()
    original_triangles = _count_scene_triangles(mesh_objects)
    target_triangles = min(int(args.target_triangles), original_triangles) if original_triangles else int(args.target_triangles)
    selected_candidates: set[str] = set()
    object_reports: list[dict[str, Any]] = []

    if not mesh_objects:
        errors.append("No mesh objects were found.")
    elif original_triangles <= target_triangles:
        warnings.append("Local simplification skipped because the model is already at or below target.")
    else:
        remaining_budget = target_triangles
        remaining_input = original_triangles
        for index, obj in enumerate(mesh_objects):
            source_mesh = _object_mesh(obj)
            input_triangles = len(source_mesh.triangles)
            if input_triangles == 0:
                continue
            if index == len(mesh_objects) - 1:
                object_target = max(0, min(input_triangles, remaining_budget))
            else:
                ratio = input_triangles / max(remaining_input, 1)
                object_target = max(1, min(input_triangles, int(round(remaining_budget * ratio))))
            remaining_budget -= object_target
            remaining_input -= input_triangles

            selected, scores, score_report = _combo_scores_for_mesh(
                source_mesh,
                str(args.combo_candidate),
                float(args.lambda_value),
                float(args.eps),
            )
            selected_candidates.add(selected)
            cost_provider = SelectedAFCostProvider.from_mesh(
                source_mesh,
                selected,
                lambda_value=float(args.lambda_value),
                eps=float(args.eps),
            )
            result = CollapseExecutor(
                cost_provider,
                QEMPlacement(),
            ).simplify(
                source_mesh,
                object_target,
                progress_callback=lambda progress, object_name=obj.name: _emit_progress(
                    {
                        "kind": "local_simplification",
                        "object_name": object_name,
                        "combo_candidate": selected,
                        **progress,
                    }
                ),
            )
            _apply_result_to_object(obj, result.vertices, result.triangles, result.vertex_sources)
            object_reports.append(
                {
                    "object_name": obj.name,
                    "input_triangles": input_triangles,
                    "target_triangles": object_target,
                    "output_triangles": len(result.triangles),
                    "collapse_count": result.collapsed_edge_count,
                    "skipped_invalid_edges": result.skipped_invalid_edges,
                    "runtime": result.runtime_seconds,
                    "cost_provider_name": result.cost_provider_name,
                    "placement_provider_name": result.placement_provider_name,
                    "score": score_report,
                }
            )

    candidate_name = ",".join(sorted(selected_candidates)) if selected_candidates else str(args.combo_candidate)
    output_stem = f"{source.stem}_local_simplified_{_filename_slug(candidate_name)}"
    output_blend = output_directory / f"{output_stem}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))
    mesh_objects = _mesh_objects()
    actual_triangles = _count_scene_triangles(mesh_objects)
    preview_mesh = output_directory / f"{output_stem}_viewport.obj"
    if mesh_objects:
        _write_preview_obj(mesh_objects, preview_mesh)

    preview_report = generate_model_preview(
        argparse.Namespace(
            blend_file=str(output_blend),
            output_directory=str(output_directory),
        )
    )
    preview_image = Path(str(preview_report.get("preview_image_path", output_directory / f"{output_stem}_source_preview.png")))
    reduction = (
        0.0
        if original_triangles <= 0
        else round(((original_triangles - actual_triangles) / original_triangles) * 100.0, 2)
    )
    score = _score(actual_triangles, int(args.warning_triangles), int(args.critical_triangles))
    local_report = {
        "input_triangles": original_triangles,
        "output_triangles": actual_triangles,
        "collapse_count": sum(int(item["collapse_count"]) for item in object_reports),
        "skipped_invalid_edges": sum(int(item["skipped_invalid_edges"]) for item in object_reports),
        "runtime": sum(float(item.get("runtime", 0.0)) for item in object_reports),
        "cost_provider_name": "SelectedAFCostProvider",
        "placement_provider_name": "QEMPlacement",
        "combo_candidate": candidate_name,
        "objects": object_reports,
    }
    report_path = output_directory / "local_simplification_report.json"
    report_path.write_text(json.dumps(local_report, indent=2), encoding="utf-8")

    return {
        "source_blend_file": str(source),
        "output_directory": str(output_directory),
        "original_triangle_count": original_triangles,
        "profile_id": args.profile_id,
        "items": [
            {
                "target_triangles": int(args.target_triangles),
                "actual_triangles": actual_triangles,
                "reduction_percent": reduction,
                "compatibility_score": score,
                "rating": _rating(score),
                "preview_blend_path": str(output_blend),
                "preview_image_path": str(preview_image),
                "preview_mesh_path": str(preview_mesh) if preview_mesh.exists() else None,
                "warnings": warnings + [f"Local edge-collapse used combo candidate: {local_report['combo_candidate']}"],
                "errors": errors,
            }
        ],
        "warnings": warnings,
        "errors": errors,
        "local_simplification_report": str(report_path),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a local edge-collapse simplification preview.")
    parser.add_argument("--blend-file", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--target-triangles", type=int, required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--warning-triangles", type=int, required=True)
    parser.add_argument("--critical-triangles", type=int, required=True)
    parser.add_argument("--combo-candidate", default="auto")
    parser.add_argument("--lambda-value", type=float, default=1.0)
    parser.add_argument("--eps", type=float, default=1e-6)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    report = generate(args)
    Path(args.output_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if not report.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]))
