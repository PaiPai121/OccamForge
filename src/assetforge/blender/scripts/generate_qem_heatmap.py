from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Matrix, Vector


HEAT_COLORS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.00, (0, 64, 255)),
    (0.25, (0, 220, 255)),
    (0.50, (40, 210, 80)),
    (0.75, (255, 230, 0)),
    (1.00, (255, 40, 20)),
)

BOUNDARY_PENALTY_WEIGHT = 12.0
NORMAL_PENALTY_WEIGHT = 8.0


def _emit_progress(percent: int, stage: str) -> None:
    print(
        "ASSETFORGE_PROGRESS "
        + json.dumps(
            {
                "kind": "qem_heatmap",
                "percent": max(0, min(100, int(percent))),
                "stage": stage,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def _clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def _import_source(source_file: Path) -> None:
    suffix = source_file.suffix.lower()
    if suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(source_file))
        return

    _clear_scene()
    if suffix == ".obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=str(source_file))
        else:
            bpy.ops.import_scene.obj(filepath=str(source_file))
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(source_file))
    elif suffix in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(source_file))
    else:
        raise ValueError(f"Unsupported QEM heatmap source type: {source_file.suffix}")


def _mesh_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def _zero_quadric() -> list[list[float]]:
    return [[0.0 for _ in range(4)] for _ in range(4)]


def _quadric_from_plane(plane: tuple[float, float, float, float]) -> list[list[float]]:
    return [[plane[row] * plane[col] for col in range(4)] for row in range(4)]


def _add_quadric(target: list[list[float]], source: list[list[float]]) -> None:
    for row in range(4):
        for col in range(4):
            target[row][col] += source[row][col]


def _sum_quadrics(first: list[list[float]], second: list[list[float]]) -> list[list[float]]:
    return [[first[row][col] + second[row][col] for col in range(4)] for row in range(4)]


def _quadric_error(quadric: list[list[float]], position: Vector) -> float:
    vector = (float(position.x), float(position.y), float(position.z), 1.0)
    total = 0.0
    for row in range(4):
        for col in range(4):
            total += vector[row] * quadric[row][col] * vector[col]
    return max(0.0, float(total))


def _plane_from_triangle(a: Vector, b: Vector, c: Vector) -> tuple[float, float, float, float] | None:
    normal = (b - a).cross(c - a)
    if normal.length <= 1e-12:
        return None
    normal.normalize()
    d = -normal.dot(a)
    return float(normal.x), float(normal.y), float(normal.z), float(d)


def _normal_from_triangle(a: Vector, b: Vector, c: Vector) -> Vector | None:
    normal = (b - a).cross(c - a)
    if normal.length <= 1e-12:
        return None
    normal.normalize()
    return normal


def _optimal_position(
    quadric: list[list[float]],
    v0: Vector,
    v1: Vector,
) -> tuple[Vector, str]:
    matrix = Matrix(
        (
            (quadric[0][0], quadric[0][1], quadric[0][2]),
            (quadric[1][0], quadric[1][1], quadric[1][2]),
            (quadric[2][0], quadric[2][1], quadric[2][2]),
        )
    )
    rhs = Vector((-quadric[0][3], -quadric[1][3], -quadric[2][3]))
    if abs(matrix.determinant()) > 1e-12:
        try:
            return matrix.inverted() @ rhs, "optimal"
        except (ValueError, ZeroDivisionError):
            pass

    midpoint = (v0 + v1) * 0.5
    candidates = (("v0", v0), ("v1", v1), ("midpoint", midpoint))
    name, position = min(candidates, key=lambda item: _quadric_error(quadric, item[1]))
    return position.copy(), name


def _heat_color(heat: float) -> tuple[int, int, int]:
    heat = max(0.0, min(1.0, heat))
    for index in range(len(HEAT_COLORS) - 1):
        left_value, left_color = HEAT_COLORS[index]
        right_value, right_color = HEAT_COLORS[index + 1]
        if left_value <= heat <= right_value:
            span = max(right_value - left_value, 1e-9)
            t = (heat - left_value) / span
            return tuple(
                int(round(left_color[channel] + (right_color[channel] - left_color[channel]) * t))
                for channel in range(3)
            )
    return HEAT_COLORS[-1][1]


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


def _collect_qem_data(mesh_objects: list[bpy.types.Object]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    total_vertices = 0
    total_faces = 0
    total_triangles = 0
    singular_fallback_edges = 0

    for obj in mesh_objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        total_vertices += len(mesh.vertices)
        total_faces += len(mesh.polygons)
        total_triangles += len(mesh.loop_triangles)
        vertex_quadrics = [_zero_quadric() for _ in mesh.vertices]
        world_positions = [obj.matrix_world @ vertex.co for vertex in mesh.vertices]
        edge_to_triangles: dict[tuple[int, int], int] = {}
        edge_to_normals: dict[tuple[int, int], list[Vector]] = {}

        for triangle in mesh.loop_triangles:
            indices = tuple(int(index) for index in triangle.vertices)
            a, b, c = (world_positions[index] for index in indices)
            plane = _plane_from_triangle(a, b, c)
            if plane is None:
                continue
            normal = _normal_from_triangle(a, b, c)
            if normal is None:
                continue
            face_quadric = _quadric_from_plane(plane)
            for vertex_index in indices:
                _add_quadric(vertex_quadrics[vertex_index], face_quadric)
            tri_edges = (
                tuple(sorted((indices[0], indices[1]))),
                tuple(sorted((indices[1], indices[2]))),
                tuple(sorted((indices[2], indices[0]))),
            )
            for edge in tri_edges:
                edge_to_triangles[edge] = edge_to_triangles.get(edge, 0) + 1
                edge_to_normals.setdefault(edge, []).append(normal)

        for local_edge_index, (v0_index, v1_index) in enumerate(sorted(edge_to_triangles)):
            q_edge = _sum_quadrics(vertex_quadrics[v0_index], vertex_quadrics[v1_index])
            v0 = world_positions[v0_index]
            v1 = world_positions[v1_index]
            placement, placement_source = _optimal_position(q_edge, v0, v1)
            if placement_source != "optimal":
                singular_fallback_edges += 1
            cost = _quadric_error(q_edge, placement)
            edge_length_squared = max((v1 - v0).length_squared, 1e-12)
            is_boundary = edge_to_triangles[(v0_index, v1_index)] == 1
            normals = edge_to_normals.get((v0_index, v1_index), [])
            normal_penalty = 0.0
            if len(normals) >= 2:
                worst_normal_delta = 0.0
                for first_index in range(len(normals)):
                    for second_index in range(first_index + 1, len(normals)):
                        dot = max(-1.0, min(1.0, normals[first_index].dot(normals[second_index])))
                        worst_normal_delta = max(worst_normal_delta, 1.0 - abs(dot))
                normal_penalty = NORMAL_PENALTY_WEIGHT * worst_normal_delta * edge_length_squared
            boundary_penalty = BOUNDARY_PENALTY_WEIGHT * edge_length_squared if is_boundary else 0.0
            feature_cost = cost + boundary_penalty + normal_penalty
            edges.append(
                {
                    "object_name": obj.name,
                    "edge_id": len(edges),
                    "local_edge_id": local_edge_index,
                    "v0": int(v0_index),
                    "v1": int(v1_index),
                    "global_v0": f"{obj.name}:{v0_index}",
                    "global_v1": f"{obj.name}:{v1_index}",
                    "v0_position": [float(v0.x), float(v0.y), float(v0.z)],
                    "v1_position": [float(v1.x), float(v1.y), float(v1.z)],
                    "optimal_position": [float(placement.x), float(placement.y), float(placement.z)],
                    "placement_source": placement_source,
                    "cost": cost,
                    "feature_cost": feature_cost,
                    "boundary_penalty": boundary_penalty,
                    "normal_penalty": normal_penalty,
                    "is_boundary": is_boundary,
                }
            )

    metadata = {
        "vertex_count": total_vertices,
        "face_count": total_faces,
        "triangle_count": total_triangles,
        "edge_count": len(edges),
        "singular_fallback_edges": singular_fallback_edges,
    }
    return edges, metadata


def _apply_cost_visualization(
    edges: list[dict[str, Any]],
    cost_key: str,
    heat_key: str,
    display_heat_key: str,
    color_key: str,
) -> dict[str, float]:
    costs = [float(edge[cost_key]) for edge in edges]
    sorted_costs = sorted(costs)
    min_cost = min(costs, default=0.0)
    max_cost = max(costs, default=0.0)
    display_max_cost = _percentile(costs, 0.99) if costs else 0.0
    span = max_cost - min_cost
    for edge in edges:
        cost = float(edge[cost_key])
        heat = 0.0 if span <= 1e-20 else (cost - min_cost) / span
        heat = max(0.0, min(1.0, heat))
        edge[heat_key] = heat
        display_heat = 0.0
        if len(sorted_costs) > 1:
            rank = bisect.bisect_right(sorted_costs, cost) - 1
            display_heat = rank / (len(sorted_costs) - 1)
        display_heat = max(0.0, min(1.0, display_heat))
        edge[display_heat_key] = display_heat
        edge[color_key] = list(_heat_color(display_heat))
    return {"min": min_cost, "max": max_cost, "display_max": display_max_cost}


def _write_ply(edges: list[dict[str, Any]], output_path: Path, color_key: str) -> None:
    vertices: list[list[float]] = []
    ply_edges: list[tuple[int, int, tuple[int, int, int]]] = []
    for edge in edges:
        start_index = len(vertices)
        vertices.append(edge["v0_position"])
        vertices.append(edge["v1_position"])
        color = tuple(int(value) for value in edge[color_key])
        ply_edges.append((start_index, start_index + 1, color))

    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("ply\n")
        handle.write("format ascii 1.0\n")
        handle.write("comment OccamForge QEM edge cost heatmap\n")
        handle.write(f"element vertex {len(vertices)}\n")
        handle.write("property float x\n")
        handle.write("property float y\n")
        handle.write("property float z\n")
        handle.write(f"element edge {len(ply_edges)}\n")
        handle.write("property int vertex1\n")
        handle.write("property int vertex2\n")
        handle.write("property uchar red\n")
        handle.write("property uchar green\n")
        handle.write("property uchar blue\n")
        handle.write("end_header\n")
        for vertex in vertices:
            handle.write(f"{vertex[0]:.9g} {vertex[1]:.9g} {vertex[2]:.9g}\n")
        for v0, v1, color in ply_edges:
            handle.write(f"{v0} {v1} {color[0]} {color[1]} {color[2]}\n")


def _bounds_from_edges(edges: list[dict[str, Any]]) -> tuple[Vector, Vector]:
    minimum = Vector((math.inf, math.inf, math.inf))
    maximum = Vector((-math.inf, -math.inf, -math.inf))
    for edge in edges:
        for key in ("v0_position", "v1_position"):
            position = edge[key]
            minimum.x = min(minimum.x, position[0])
            minimum.y = min(minimum.y, position[1])
            minimum.z = min(minimum.z, position[2])
            maximum.x = max(maximum.x, position[0])
            maximum.y = max(maximum.y, position[1])
            maximum.z = max(maximum.z, position[2])
    if math.isinf(minimum.x):
        return Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0))
    return minimum, maximum


def _material(name: str, color: tuple[int, int, int]) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.diffuse_color = (color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, 1.0)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = material.diffuse_color
        bsdf.inputs["Emission Color"].default_value = material.diffuse_color
        bsdf.inputs["Emission Strength"].default_value = 0.45
    return material


def _look_at(obj: bpy.types.Object, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _render_heatmap(
    edges: list[dict[str, Any]],
    output_path: Path,
    display_heat_key: str,
    invert: bool = False,
) -> None:
    _clear_scene()
    if not edges:
        return
    minimum, maximum = _bounds_from_edges(edges)
    center = (minimum + maximum) * 0.5
    size = maximum - minimum
    diagonal = max(size.length, 1.0)
    bevel_depth = max(diagonal * 0.0009, 0.0003)
    bins = [
        ("Blue_Low", 0.20, (0, 64, 255)),
        ("Cyan", 0.40, (0, 220, 255)),
        ("Green", 0.60, (40, 210, 80)),
        ("Yellow", 0.80, (255, 230, 0)),
        ("Red_High", 1.01, (255, 40, 20)),
    ]
    grouped: list[list[dict[str, Any]]] = [[] for _ in bins]
    for edge in edges:
        heat = float(edge[display_heat_key])
        if invert:
            heat = 1.0 - heat
        for index, (_, upper, _) in enumerate(bins):
            if heat <= upper:
                grouped[index].append(edge)
                break

    for index, (name, _, color) in enumerate(bins):
        curve = bpy.data.curves.new(f"QEM_{name}", type="CURVE")
        curve.dimensions = "3D"
        curve.resolution_u = 1
        curve.bevel_depth = bevel_depth
        curve.bevel_resolution = 1
        for edge in grouped[index]:
            spline = curve.splines.new("POLY")
            spline.points.add(1)
            v0 = edge["v0_position"]
            v1 = edge["v1_position"]
            spline.points[0].co = (v0[0], v0[1], v0[2], 1.0)
            spline.points[1].co = (v1[0], v1[1], v1[2], 1.0)
        obj = bpy.data.objects.new(f"QEM_{name}", curve)
        bpy.context.collection.objects.link(obj)
        obj.data.materials.append(_material(f"QEM_{name}_Material", color))

    camera_data = bpy.data.cameras.new("QEM_Heatmap_Camera")
    camera = bpy.data.objects.new("QEM_Heatmap_Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = center + Vector((diagonal * 0.9, -diagonal * 1.8, diagonal * 0.75))
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = max(size.x * 0.82 + size.z * 0.55, size.y * 0.45 + size.z * 0.9, 1.0) * 1.18
    _look_at(camera, center)
    bpy.context.scene.camera = camera

    light_data = bpy.data.lights.new("QEM_Heatmap_Light", type="AREA")
    light = bpy.data.objects.new("QEM_Heatmap_Light", light_data)
    bpy.context.collection.objects.link(light)
    light.location = center + Vector((diagonal * 0.4, -diagonal * 0.8, diagonal * 1.2))
    light_data.energy = 700
    light_data.size = max(diagonal, 1.0)
    _look_at(light, center)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items} else "BLENDER_EEVEE"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 1000
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "Medium High Contrast"
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output_path)
    bpy.ops.render.render(write_still=False)
    bpy.data.images["Render Result"].save_render(filepath=str(output_path))


def _cost_statistics(
    edges: list[dict[str, Any]],
    min_max: dict[str, float],
    cost_key: str,
) -> dict[str, float]:
    costs = [float(edge[cost_key]) for edge in edges]
    if not costs:
        return {
            "min": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "median": 0.0,
            "p90": 0.0,
            "p99": 0.0,
        }
    return {
        "min": min_max["min"],
        "max": min_max["max"],
        "mean": statistics.fmean(costs),
        "median": statistics.median(costs),
        "p90": _percentile(costs, 0.90),
        "p99": _percentile(costs, 0.99),
    }


def _cost_statistics_for_costs(costs: list[float]) -> dict[str, float]:
    if not costs:
        return {
            "min": 0.0,
            "max": 0.0,
            "mean": 0.0,
            "median": 0.0,
            "p90": 0.0,
            "p99": 0.0,
        }
    return {
        "min": min(costs),
        "max": max(costs),
        "mean": statistics.fmean(costs),
        "median": statistics.median(costs),
        "p90": _percentile(costs, 0.90),
        "p99": _percentile(costs, 0.99),
    }


def _object_statistics(
    edges: list[dict[str, Any]],
    stats: dict[str, float],
    cost_key: str,
) -> list[dict[str, Any]]:
    by_object: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        by_object.setdefault(str(edge["object_name"]), []).append(edge)

    object_stats: list[dict[str, Any]] = []
    high_threshold = stats["p90"]
    low_threshold = stats["median"]
    for object_name, object_edges in sorted(by_object.items()):
        costs = [float(edge[cost_key]) for edge in object_edges]
        boundary_edges = [edge for edge in object_edges if edge["is_boundary"]]
        object_stats.append(
            {
                "object_name": object_name,
                "edge_count": len(object_edges),
                "boundary_edge_count": len(boundary_edges),
                "global_p90_plus_edge_count": sum(1 for cost in costs if cost >= high_threshold),
                "global_median_or_lower_edge_count": sum(1 for cost in costs if cost <= low_threshold),
                "cost_statistics": _cost_statistics_for_costs(costs),
                "boundary_cost_statistics": _cost_statistics_for_costs(
                    [float(edge[cost_key]) for edge in boundary_edges]
                ),
            }
        )
    return object_stats


def _boundary_statistics(
    edges: list[dict[str, Any]],
    stats: dict[str, float],
    cost_key: str,
) -> dict[str, Any]:
    boundary_edges = [edge for edge in edges if edge["is_boundary"]]
    boundary_costs = [float(edge[cost_key]) for edge in boundary_edges]
    high_threshold = stats["p90"]
    return {
        "boundary_edge_count": len(boundary_edges),
        "boundary_p90_plus_edge_count": sum(1 for cost in boundary_costs if cost >= high_threshold),
        "boundary_p90_plus_ratio": (
            0.0
            if not boundary_edges
            else sum(1 for cost in boundary_costs if cost >= high_threshold) / len(boundary_edges)
        ),
        "cost_statistics": _cost_statistics_for_costs(boundary_costs),
    }


def _edge_summary(edge: dict[str, Any], cost_key: str) -> dict[str, Any]:
    return {
        "edge_id": edge["edge_id"],
        "object_name": edge["object_name"],
        "v0": edge["v0"],
        "v1": edge["v1"],
        "global_v0": edge["global_v0"],
        "global_v1": edge["global_v1"],
        "cost": edge[cost_key],
        "classic_cost": edge["cost"],
        "feature_cost": edge["feature_cost"],
        "boundary_penalty": edge["boundary_penalty"],
        "normal_penalty": edge["normal_penalty"],
        "heat": edge["heat" if cost_key == "cost" else "feature_heat"],
        "display_heat": edge[
            "display_heat" if cost_key == "cost" else "feature_display_heat"
        ],
        "placement_source": edge["placement_source"],
        "is_boundary": edge["is_boundary"],
    }


def _report_observations(edges: list[dict[str, Any]], stats: dict[str, float]) -> list[str]:
    if not edges:
        return ["No edges were available for QEM cost analysis."]
    high_threshold = stats["p90"]
    low_threshold = stats["median"]
    boundary_edges = [edge for edge in edges if edge["is_boundary"]]
    boundary_high = [edge for edge in boundary_edges if float(edge["cost"]) >= high_threshold]
    optimal_count = sum(1 for edge in edges if edge["placement_source"] == "optimal")
    return [
        f"{len(boundary_high):,} of {len(boundary_edges):,} boundary edges are in the p90+ cost band.",
        f"{optimal_count:,} of {len(edges):,} edges used the direct optimal QEM solve; the rest used Garland endpoint/midpoint fallback.",
        f"Edges below median cost ({low_threshold:.6g}) are the most likely first-collapse candidates for a future simplifier.",
        "This diagnostic does not include silhouette, boundary penalty, normal validation, or any collapse operation.",
    ]


def generate(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source_file).resolve()
    output_directory = Path(args.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    _emit_progress(5, "Importing source model")
    _import_source(source)
    mesh_objects = _mesh_objects()
    _emit_progress(25, "Collecting edge quadrics")
    edges, metadata = _collect_qem_data(mesh_objects)
    _emit_progress(45, "Computing classic QEM heat values")
    min_max = _apply_cost_visualization(
        edges,
        "cost",
        "heat",
        "display_heat",
        "color_rgb",
    )
    _emit_progress(55, "Computing feature-aware QEM heat values")
    feature_min_max = _apply_cost_visualization(
        edges,
        "feature_cost",
        "feature_heat",
        "feature_display_heat",
        "feature_color_rgb",
    )
    _emit_progress(62, "Summarizing edge cost distributions")
    stats = _cost_statistics(edges, min_max, "cost")
    feature_stats = _cost_statistics(edges, feature_min_max, "feature_cost")

    sorted_edges = sorted(edges, key=lambda edge: float(edge["cost"]))
    lowest = [_edge_summary(edge, "cost") for edge in sorted_edges[:50]]
    highest = [_edge_summary(edge, "cost") for edge in reversed(sorted_edges[-50:])]
    sorted_feature_edges = sorted(edges, key=lambda edge: float(edge["feature_cost"]))
    feature_lowest = [_edge_summary(edge, "feature_cost") for edge in sorted_feature_edges[:50]]
    feature_highest = [
        _edge_summary(edge, "feature_cost") for edge in reversed(sorted_feature_edges[-50:])
    ]

    ply_path = output_directory / "qem_heatmap.ply"
    png_path = output_directory / "qem_heatmap.png"
    inverse_png_path = output_directory / "qem_heatmap_inverse.png"
    feature_ply_path = output_directory / "feature_qem_heatmap.ply"
    feature_png_path = output_directory / "feature_qem_heatmap.png"
    feature_inverse_png_path = output_directory / "feature_qem_heatmap_inverse.png"
    _emit_progress(68, "Writing classic QEM PLY")
    _write_ply(edges, ply_path, "color_rgb")
    _emit_progress(73, "Rendering classic QEM heatmap")
    _render_heatmap(edges, png_path, "display_heat")
    _emit_progress(79, "Rendering inverted classic QEM heatmap")
    _render_heatmap(edges, inverse_png_path, "display_heat", invert=True)
    _emit_progress(84, "Writing feature-aware QEM PLY")
    _write_ply(edges, feature_ply_path, "feature_color_rgb")
    _emit_progress(89, "Rendering feature-aware QEM heatmap")
    _render_heatmap(edges, feature_png_path, "feature_display_heat")
    _emit_progress(94, "Rendering inverted feature-aware QEM heatmap")
    _render_heatmap(edges, feature_inverse_png_path, "feature_display_heat", invert=True)

    _emit_progress(98, "Writing QEM report")
    report = {
        "source_file": str(source),
        "output_directory": str(output_directory),
        "report_json_path": str(output_directory / "qem_heatmap_report.json"),
        "vertex_count": metadata["vertex_count"],
        "face_count": metadata["face_count"],
        "triangle_count": metadata["triangle_count"],
        "edge_count": metadata["edge_count"],
        "singular_fallback_edges": metadata["singular_fallback_edges"],
        "cost_statistics": stats,
        "feature_cost_statistics": feature_stats,
        "feature_aware_cost": {
            "formula": "classic_qem_cost + boundary_penalty + normal_penalty",
            "boundary_penalty_weight": BOUNDARY_PENALTY_WEIGHT,
            "normal_penalty_weight": NORMAL_PENALTY_WEIGHT,
            "boundary_penalty": "boundary_weight * edge_length_squared for boundary edges",
            "normal_penalty": "normal_weight * worst_adjacent_normal_delta * edge_length_squared",
            "scope": "diagnostic cost only; no collapse, no validation, no topology modification",
        },
        "visualization": {
            "raw_heat_normalization": "min_max",
            "display_heat_normalization": "percentile_rank",
            "display_max_cost": min_max["display_max"],
            "feature_display_max_cost": feature_min_max["display_max"],
            "color_scale": "blue_cyan_green_yellow_red",
        },
        "boundary_statistics": _boundary_statistics(edges, stats, "cost"),
        "feature_boundary_statistics": _boundary_statistics(edges, feature_stats, "feature_cost"),
        "object_statistics": _object_statistics(edges, stats, "cost"),
        "feature_object_statistics": _object_statistics(edges, feature_stats, "feature_cost"),
        "top_50_highest_cost_edges": highest,
        "top_50_lowest_cost_edges": lowest,
        "feature_top_50_highest_cost_edges": feature_highest,
        "feature_top_50_lowest_cost_edges": feature_lowest,
        "heatmap_ply": str(ply_path),
        "heatmap_png": str(png_path),
        "heatmap_inverse_png": str(inverse_png_path),
        "feature_heatmap_ply": str(feature_ply_path),
        "feature_heatmap_png": str(feature_png_path),
        "feature_heatmap_inverse_png": str(feature_inverse_png_path),
        "observations": _report_observations(edges, stats),
        "errors": [],
    }
    Path(report["report_json_path"]).write_text(json.dumps(report, indent=2), encoding="utf-8")
    _emit_progress(100, "QEM heatmap complete")
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a QEM edge collapse cost heatmap.")
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
