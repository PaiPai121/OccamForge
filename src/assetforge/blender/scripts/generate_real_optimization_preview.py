from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import deque
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).parent))

from optimize_vehicle import (
    _apply_transforms,
    _classify_vehicle,
    _count_scene_triangles,
    _is_wheel_like_name,
    _mesh_objects,
    _optimize_objects,
)

GRID_DIVISIONS = 12
TARGET_ACTIONS = {"limited_dissolve_candidate", "decimate_candidate"}
BUCKETS = ("MUST_KEEP", "SOFT_KEEP", "REDUCE_FIRST", "DELETE_CANDIDATE")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _bucket_material(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = color
    return material


def _capture_material_state(
    mesh_objects: list[bpy.types.Object],
) -> dict[str, tuple[list[bpy.types.Material | None], list[int]]]:
    return {
        obj.name: (
            [material for material in obj.data.materials],
            [int(polygon.material_index) for polygon in obj.data.polygons],
        )
        for obj in mesh_objects
    }


def _restore_material_state(
    mesh_objects: list[bpy.types.Object],
    state: dict[str, tuple[list[bpy.types.Material | None], list[int]]],
) -> None:
    for obj in mesh_objects:
        materials, polygon_indices = state.get(obj.name, ([], []))
        obj.data.materials.clear()
        for material in materials:
            obj.data.materials.append(material)
        max_material_index = max(0, len(obj.data.materials) - 1)
        for index, polygon in enumerate(obj.data.polygons):
            if index < len(polygon_indices):
                polygon.material_index = min(max(polygon_indices[index], 0), max_material_index)
            elif obj.data.materials:
                polygon.material_index = min(int(polygon.material_index), max_material_index)
            else:
                polygon.material_index = 0


def _render_stage_map(mesh_objects: list[bpy.types.Object], image_path: Path) -> None:
    _setup_camera_and_light(mesh_objects)
    _configure_render(image_path)
    bpy.ops.render.render(write_still=False)
    bpy.data.images["Render Result"].save_render(filepath=str(image_path))


def _triangle_adjacency(obj: bpy.types.Object) -> dict[int, set[int]]:
    obj.data.calc_loop_triangles()
    edge_to_triangles: dict[tuple[int, int], list[int]] = {}
    for triangle in obj.data.loop_triangles:
        vertices = list(triangle.vertices)
        for index in range(3):
            edge = tuple(sorted((int(vertices[index]), int(vertices[(index + 1) % 3]))))
            edge_to_triangles.setdefault(edge, []).append(int(triangle.index))

    adjacency: dict[int, set[int]] = {int(triangle.index): set() for triangle in obj.data.loop_triangles}
    for triangles in edge_to_triangles.values():
        if len(triangles) < 2:
            continue
        for triangle in triangles:
            adjacency[triangle].update(other for other in triangles if other != triangle)
    return adjacency


def _ring_expand(seed: set[int], adjacency: dict[int, set[int]], ring_count: int) -> set[int]:
    expanded = set(seed)
    frontier = set(seed)
    for _ in range(max(0, ring_count)):
        next_frontier: set[int] = set()
        for triangle in frontier:
            next_frontier.update(adjacency.get(triangle, set()))
        next_frontier -= expanded
        expanded.update(next_frontier)
        frontier = next_frontier
        if not frontier:
            break
    return expanded


def _triangle_world_vertices(obj: bpy.types.Object, triangle: bpy.types.MeshLoopTriangle) -> list[Vector]:
    return [obj.matrix_world @ obj.data.vertices[index].co for index in triangle.vertices]


def _triangle_area_world(obj: bpy.types.Object, triangle: bpy.types.MeshLoopTriangle) -> float:
    vertices = _triangle_world_vertices(obj, triangle)
    return ((vertices[1] - vertices[0]).cross(vertices[2] - vertices[0])).length * 0.5


def _triangle_normal_world(obj: bpy.types.Object, triangle: bpy.types.MeshLoopTriangle) -> Vector:
    vertices = _triangle_world_vertices(obj, triangle)
    normal = (vertices[1] - vertices[0]).cross(vertices[2] - vertices[0])
    if normal.length <= 1e-9:
        return Vector((0.0, 0.0, 1.0))
    return normal.normalized()


def _triangle_curvature_score(
    triangle_index: int,
    normals: dict[int, Vector],
    adjacency: dict[int, set[int]],
) -> float:
    normal = normals.get(triangle_index)
    if normal is None:
        return 0.0
    score = 0.0
    for neighbor in adjacency.get(triangle_index, set()):
        neighbor_normal = normals.get(neighbor)
        if neighbor_normal is None:
            continue
        score = max(score, 1.0 - abs(max(-1.0, min(1.0, normal.dot(neighbor_normal)))))
    return score


def _triangle_aspect_ratio_world(obj: bpy.types.Object, triangle: bpy.types.MeshLoopTriangle) -> float:
    vertices = _triangle_world_vertices(obj, triangle)
    lengths = [
        (vertices[1] - vertices[0]).length,
        (vertices[2] - vertices[1]).length,
        (vertices[0] - vertices[2]).length,
    ]
    shortest = max(min(lengths), 1e-9)
    return max(lengths) / shortest


def _triangle_centroid_world(obj: bpy.types.Object, triangle: bpy.types.MeshLoopTriangle) -> Vector:
    vertices = _triangle_world_vertices(obj, triangle)
    return (vertices[0] + vertices[1] + vertices[2]) / 3.0


def _high_density_cells(payload: dict[str, Any] | None) -> set[tuple[int, int, int]]:
    if payload is None:
        return set()
    cells: set[tuple[int, int, int]] = set()
    for region in payload.get("dense_regions", [])[:48]:
        region_id = str(region.get("region_id", ""))
        if not region_id.startswith("cell_"):
            continue
        parts = region_id.split("_")
        if len(parts) != 4:
            continue
        try:
            cells.add((int(parts[1]), int(parts[2]), int(parts[3])))
        except ValueError:
            continue
    return cells


def _silhouette_hits_by_object(payload: dict[str, Any] | None) -> dict[str, dict[int, int]]:
    hits: dict[str, dict[int, int]] = {}
    if payload is None:
        return hits
    for triangle in payload.get("silhouette", {}).get("top_triangles", []):
        object_name = str(triangle.get("object_name", ""))
        if not object_name:
            continue
        try:
            triangle_index = int(triangle.get("triangle_index", 0))
            hit_count = int(triangle.get("silhouette_hits", 0))
        except (TypeError, ValueError):
            continue
        hits.setdefault(object_name, {})[triangle_index] = hit_count
    return hits


def _bucket_vertices_by_object(
    mesh_objects: list[bpy.types.Object],
    bucket_triangles: dict[str, dict[str, set[int]]],
    bucket: str,
) -> dict[str, set[int]]:
    vertices_by_object: dict[str, set[int]] = {}
    for obj in mesh_objects:
        triangles = bucket_triangles.get(obj.name, {}).get(bucket, set())
        if not triangles:
            continue
        obj.data.calc_loop_triangles()
        vertices: set[int] = set()
        for triangle in obj.data.loop_triangles:
            if int(triangle.index) in triangles:
                vertices.update(int(vertex) for vertex in triangle.vertices)
        if vertices:
            vertices_by_object[obj.name] = vertices
    return vertices_by_object


def _triangle_count_for_bucket(
    mesh_objects: list[bpy.types.Object],
    bucket_triangles: dict[str, dict[str, set[int]]],
    bucket: str,
) -> int:
    return sum(len(bucket_triangles.get(obj.name, {}).get(bucket, set())) for obj in mesh_objects)


def _merge_vertex_maps(*maps: dict[str, set[int]]) -> dict[str, set[int]]:
    merged: dict[str, set[int]] = {}
    for vertex_map in maps:
        for object_name, vertices in vertex_map.items():
            merged.setdefault(object_name, set()).update(vertices)
    return {object_name: vertices for object_name, vertices in merged.items() if vertices}


def _subtract_vertex_map(
    target_vertices: dict[str, set[int]],
    protected_vertices: dict[str, set[int]],
) -> dict[str, set[int]]:
    result: dict[str, set[int]] = {}
    for object_name, vertices in target_vertices.items():
        remaining = set(vertices) - protected_vertices.get(object_name, set())
        if remaining:
            result[object_name] = remaining
    return result


def _vertex_map_count(vertex_map: dict[str, set[int]]) -> int:
    return sum(len(vertices) for vertices in vertex_map.values())


def _assign_bucket_materials(
    mesh_objects: list[bpy.types.Object],
    bucket_triangles: dict[str, dict[str, set[int]]],
) -> None:
    materials = {
        "MUST_KEEP": _bucket_material("AssetForge_MUST_KEEP", (0.95, 0.12, 0.10, 1.0)),
        "SOFT_KEEP": _bucket_material("AssetForge_SOFT_KEEP", (0.95, 0.72, 0.12, 1.0)),
        "REDUCE_FIRST": _bucket_material("AssetForge_REDUCE_FIRST", (0.12, 0.55, 0.95, 1.0)),
        "DELETE_CANDIDATE": _bucket_material("AssetForge_DELETE_CANDIDATE", (0.45, 0.16, 0.75, 1.0)),
        "UNCLASSIFIED": _bucket_material("AssetForge_UNCLASSIFIED", (0.62, 0.66, 0.68, 1.0)),
    }
    for obj in mesh_objects:
        obj.data.materials.clear()
        for name in ("MUST_KEEP", "SOFT_KEEP", "REDUCE_FIRST", "DELETE_CANDIDATE", "UNCLASSIFIED"):
            obj.data.materials.append(materials[name])
        bucket_by_triangle: dict[int, str] = {}
        for bucket in BUCKETS:
            for triangle_index in bucket_triangles.get(obj.name, {}).get(bucket, set()):
                bucket_by_triangle[triangle_index] = bucket
        material_index = {name: index for index, name in enumerate(("MUST_KEEP", "SOFT_KEEP", "REDUCE_FIRST", "DELETE_CANDIDATE", "UNCLASSIFIED"))}
        obj.data.calc_loop_triangles()
        polygon_bucket: dict[int, str] = {}
        for triangle in obj.data.loop_triangles:
            polygon_bucket[int(triangle.polygon_index)] = bucket_by_triangle.get(int(triangle.index), "UNCLASSIFIED")
        for polygon in obj.data.polygons:
            polygon.material_index = material_index[polygon_bucket.get(int(polygon.index), "UNCLASSIFIED")]


def _render_bucket_map(
    mesh_objects: list[bpy.types.Object],
    bucket_triangles: dict[str, dict[str, set[int]]],
    image_path: Path,
) -> None:
    material_state = _capture_material_state(mesh_objects)
    try:
        _assign_bucket_materials(mesh_objects, bucket_triangles)
        _render_stage_map(mesh_objects, image_path)
    finally:
        _restore_material_state(mesh_objects, material_state)


def _stage2a_structural_protection_expansion(
    mesh_objects: list[bpy.types.Object],
    payload: dict[str, Any] | None,
    output_directory: Path,
    input_tris: int,
    ring_count: int = 1,
) -> tuple[dict[str, dict[str, set[int]]], dict[str, set[int]], dict[str, Any]]:
    bounds = _bounds_from_report(payload)
    high_density_cells = _high_density_cells(payload)
    silhouette_hits = _silhouette_hits_by_object(payload)
    bucket_triangles: dict[str, dict[str, set[int]]] = {
        obj.name: {bucket: set() for bucket in BUCKETS} for obj in mesh_objects
    }

    base_silhouette_tris = 0
    base_protected_vertices: dict[str, set[int]] = {}
    for obj in mesh_objects:
        obj.data.calc_loop_triangles()
        adjacency = _triangle_adjacency(obj)
        normals = {
            int(triangle.index): _triangle_normal_world(obj, triangle)
            for triangle in obj.data.loop_triangles
        }
        hits = silhouette_hits.get(obj.name, {})
        if not hits:
            continue
        adjacency = _triangle_adjacency(obj)
        must_seed = {triangle_index for triangle_index, count in hits.items() if count >= 2}
        strong_seed = {triangle_index for triangle_index, count in hits.items() if count >= 3}
        weak_seed = {triangle_index for triangle_index, count in hits.items() if count >= 1}
        base_silhouette_tris += len(must_seed)

        strong_ring = _ring_expand(strong_seed, adjacency, ring_count)
        must_keep = set(must_seed) | strong_seed
        soft_keep = _ring_expand(must_seed, adjacency, ring_count) - must_keep
        must_keep.update(strong_ring)
        soft_keep -= must_keep
        structural_cells: set[tuple[int, int, int]] = set()
        if bounds is not None:
            for triangle_index in must_keep | strong_seed:
                if triangle_index < len(obj.data.loop_triangles):
                    centroid = _triangle_centroid_world(obj, obj.data.loop_triangles[triangle_index])
                    structural_cells.add(_grid_key(centroid, bounds[0], bounds[1]))

        for triangle in obj.data.loop_triangles:
            triangle_index = int(triangle.index)
            if triangle_index in must_keep or triangle_index in soft_keep:
                continue
            if bounds is None:
                continue
            centroid = _triangle_centroid_world(obj, triangle)
            triangle_cell = _grid_key(centroid, bounds[0], bounds[1])
            if triangle_index in weak_seed and triangle_cell in high_density_cells:
                soft_keep.add(triangle_index)
            elif triangle_cell in structural_cells:
                soft_keep.add(triangle_index)

        tiny_area_threshold = max(sum(_triangle_area_world(obj, tri) for tri in obj.data.loop_triangles) * 0.00002, 1e-7)
        adjacency = _triangle_adjacency(obj)
        visited: set[int] = set()
        for seed in list(must_keep):
            if seed in visited:
                continue
            component: set[int] = set()
            queue: deque[int] = deque([seed])
            visited.add(seed)
            while queue:
                triangle_index = queue.popleft()
                component.add(triangle_index)
                for neighbor in adjacency.get(triangle_index, set()):
                    if neighbor in visited or neighbor not in must_keep:
                        continue
                    visited.add(neighbor)
                    queue.append(neighbor)
            if len(component) > 0:
                area = sum(
                    _triangle_area_world(obj, obj.data.loop_triangles[index])
                    for index in component
                    if index < len(obj.data.loop_triangles)
                )
                max_hits = max((hits.get(index, 0) for index in component), default=0)
                if len(component) <= 2 and area <= tiny_area_threshold and max_hits < 2:
                    must_keep -= component
                    soft_keep.update(component)

        bucket_triangles[obj.name]["MUST_KEEP"].update(must_keep)
        bucket_triangles[obj.name]["SOFT_KEEP"].update(soft_keep - must_keep)
        vertices: set[int] = set()
        for triangle in obj.data.loop_triangles:
            if int(triangle.index) in must_keep:
                vertices.update(int(vertex) for vertex in triangle.vertices)
        if vertices:
            base_protected_vertices[obj.name] = vertices

    protected_vertices = _bucket_vertices_by_object(mesh_objects, bucket_triangles, "MUST_KEEP")
    soft_vertices = _bucket_vertices_by_object(mesh_objects, bucket_triangles, "SOFT_KEEP")
    for object_name, vertices in soft_vertices.items():
        protected_vertices.setdefault(object_name, set()).update(vertices)

    expanded_must_keep = sum(len(bucket_triangles[obj.name]["MUST_KEEP"]) for obj in mesh_objects)
    expanded_soft_keep = sum(len(bucket_triangles[obj.name]["SOFT_KEEP"]) for obj in mesh_objects)
    report = {
        "stage": "2A_structural_protection_expansion",
        "input_tris": input_tris,
        "base_silhouette_tris": base_silhouette_tris,
        "base_protected_vertices": sum(len(vertices) for vertices in base_protected_vertices.values()),
        "expanded_must_keep_tris": expanded_must_keep,
        "expanded_soft_keep_tris": expanded_soft_keep,
        "protection_ring_count": ring_count,
        "protected_ratio": round((expanded_must_keep + expanded_soft_keep) / input_tris, 4) if input_tris else 0.0,
    }
    _write_json(output_directory / "stage_2a_protection_report.json", report)
    _render_bucket_map(mesh_objects, bucket_triangles, output_directory / "stage_2a_protection_map.png")
    return bucket_triangles, protected_vertices, report


def _connected_triangle_components(obj: bpy.types.Object) -> list[set[int]]:
    adjacency = _triangle_adjacency(obj)
    visited: set[int] = set()
    components: list[set[int]] = []
    for triangle_index in adjacency:
        if triangle_index in visited:
            continue
        component: set[int] = set()
        queue: deque[int] = deque([triangle_index])
        visited.add(triangle_index)
        while queue:
            current = queue.popleft()
            component.add(current)
            for neighbor in adjacency.get(current, set()):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append(neighbor)
        components.append(component)
    return components


def _component_bounds(obj: bpy.types.Object, component: set[int]) -> tuple[Vector, Vector, float]:
    points: list[Vector] = []
    obj.data.calc_loop_triangles()
    for triangle_index in component:
        if triangle_index >= len(obj.data.loop_triangles):
            continue
        points.extend(_triangle_world_vertices(obj, obj.data.loop_triangles[triangle_index]))
    if not points:
        zero = Vector((0.0, 0.0, 0.0))
        return zero, zero, 0.0
    minimum = Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points)))
    maximum = Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points)))
    return minimum, maximum, (maximum - minimum).length


def _delete_polygons(obj: bpy.types.Object, polygon_indices: set[int]) -> None:
    if not polygon_indices:
        return
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    for polygon in obj.data.polygons:
        polygon.select = int(polygon.index) in polygon_indices
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.delete(type="FACE")
    bpy.ops.object.mode_set(mode="OBJECT")


def _polygon_indices_for_triangles(obj: bpy.types.Object, triangle_indices: set[int]) -> set[int]:
    obj.data.calc_loop_triangles()
    polygon_indices: set[int] = set()
    for triangle in obj.data.loop_triangles:
        if int(triangle.index) in triangle_indices:
            polygon_indices.add(int(triangle.polygon_index))
    return polygon_indices


def _limited_dissolve_polygons(
    obj: bpy.types.Object,
    polygon_indices: set[int],
    angle_limit: float,
) -> None:
    if not polygon_indices:
        return
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    for polygon in obj.data.polygons:
        polygon.select = int(polygon.index) in polygon_indices
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.dissolve_limited(angle_limit=angle_limit, use_dissolve_boundaries=False)
    bpy.ops.object.mode_set(mode="OBJECT")


def _stage2b_tiny_feature_delete(
    mesh_objects: list[bpy.types.Object],
    bucket_triangles: dict[str, dict[str, set[int]]],
    payload: dict[str, Any] | None,
    output_directory: Path,
) -> dict[str, Any]:
    silhouette_hits = _silhouette_hits_by_object(payload)
    _, scene_size, _ = _scene_bounds(mesh_objects)
    scene_diag = max(scene_size.length, 1.0)
    max_component_diag = scene_diag * 0.018
    deleted_components = 0
    deleted_tris = 0
    skipped_due_to_must_keep = 0
    attached_detail_reduce_tris = 0
    attached_detail_delete_tris = 0
    bevel_strip_tris = 0
    cylinder_detail_tris = 0
    bounds = _bounds_from_report(payload)
    dense_cells = _high_density_cells(payload)

    for obj in mesh_objects:
        obj.data.calc_loop_triangles()
        adjacency = _triangle_adjacency(obj)
        normals = {
            int(triangle.index): _triangle_normal_world(obj, triangle)
            for triangle in obj.data.loop_triangles
        }
        hits = silhouette_hits.get(obj.name, {})
        must_keep = bucket_triangles.get(obj.name, {}).get("MUST_KEEP", set())
        soft_keep = bucket_triangles.get(obj.name, {}).get("SOFT_KEEP", set())
        reduce_first = bucket_triangles.get(obj.name, {}).setdefault("REDUCE_FIRST", set())
        delete_candidate = bucket_triangles.get(obj.name, {}).setdefault("DELETE_CANDIDATE", set())
        triangle_areas = [
            _triangle_area_world(obj, triangle)
            for triangle in obj.data.loop_triangles
        ]
        sorted_areas = sorted(area for area in triangle_areas if area > 0.0)
        if sorted_areas:
            median_area = sorted_areas[len(sorted_areas) // 2]
            tiny_area = sorted_areas[max(0, int(len(sorted_areas) * 0.12) - 1)]
        else:
            median_area = 0.0
            tiny_area = 0.0
        object_is_cylinder_detail_source = _is_wheel_like_name(obj.name) or obj.name.lower().startswith(("barrel", "cannon", "gun"))
        for component in _connected_triangle_components(obj):
            if component & must_keep:
                skipped_due_to_must_keep += 1
                continue
            if component & soft_keep:
                continue
            max_hits = max((hits.get(index, 0) for index in component), default=0)
            _, _, component_diag = _component_bounds(obj, component)
            area = sum(
                _triangle_area_world(obj, obj.data.loop_triangles[index])
                for index in component
                if index < len(obj.data.loop_triangles)
            )
            component_curvature = max(
                (
                    _triangle_curvature_score(index, normals, adjacency)
                    for index in component
                    if index < len(obj.data.loop_triangles)
                ),
                default=0.0,
            )
            is_tiny = len(component) <= 6 and component_diag <= max_component_diag * 0.45
            low_visible = max_hits == 0
            low_area = area <= (scene_diag * scene_diag * 0.00001)
            if is_tiny and low_visible and low_area and component_curvature >= 0.10:
                delete_candidate.update(component)
                # Mark for extreme local reduction. Direct deletion is intentionally deferred
                # until component visibility classification is stronger.
        for triangle in obj.data.loop_triangles:
            triangle_index = int(triangle.index)
            if triangle_index in must_keep:
                continue
            if triangle_index in reduce_first or triangle_index in delete_candidate:
                continue
            if hits.get(triangle_index, 0) > 0:
                continue
            was_soft_keep = triangle_index in soft_keep
            area = triangle_areas[triangle_index] if triangle_index < len(triangle_areas) else _triangle_area_world(obj, triangle)
            aspect_ratio = _triangle_aspect_ratio_world(obj, triangle)
            curvature = _triangle_curvature_score(triangle_index, normals, adjacency)
            dense_cell = False
            if bounds is not None:
                dense_cell = _grid_key(_triangle_centroid_world(obj, triangle), bounds[0], bounds[1]) in dense_cells
            is_small = median_area > 0.0 and area <= median_area * 0.45
            is_tiny_triangle = tiny_area > 0.0 and area <= tiny_area
            is_flat_panel = curvature <= 0.035 and aspect_ratio < 4.5
            if is_flat_panel:
                continue
            high_curvature_detail = curvature >= 0.10
            is_bevel_strip = high_curvature_detail and aspect_ratio >= 4.5 and area <= max(median_area * 0.9, tiny_area)
            is_attached_detail = high_curvature_detail and is_small and (dense_cell or aspect_ratio >= 3.0)
            is_cylinder_detail = high_curvature_detail and (object_is_cylinder_detail_source or aspect_ratio >= 3.0) and (is_small or aspect_ratio >= 4.0)
            strong_soft_keep_override = was_soft_keep and (is_bevel_strip or is_cylinder_detail) and area <= max(median_area, tiny_area)
            if was_soft_keep and not strong_soft_keep_override:
                continue
            if strong_soft_keep_override:
                soft_keep.discard(triangle_index)
            if is_tiny_triangle and high_curvature_detail and (dense_cell or is_cylinder_detail) and not was_soft_keep:
                delete_candidate.add(triangle_index)
                attached_detail_delete_tris += 1
            elif is_bevel_strip or is_attached_detail or is_cylinder_detail:
                reduce_first.add(triangle_index)
                attached_detail_reduce_tris += 1
                if is_bevel_strip:
                    bevel_strip_tris += 1
                if is_cylinder_detail:
                    cylinder_detail_tris += 1

    remaining_tris = _count_scene_triangles(_mesh_objects())
    report = {
        "stage": "2B_detail_candidate_detection",
        "deleted_components": deleted_components,
        "deleted_tris": deleted_tris,
        "marked_delete_candidate_tris": sum(
            len(bucket_triangles.get(obj.name, {}).get("DELETE_CANDIDATE", set()))
            for obj in mesh_objects
        ),
        "attached_detail_reduce_tris": attached_detail_reduce_tris,
        "attached_detail_delete_tris": attached_detail_delete_tris,
        "bevel_strip_tris": bevel_strip_tris,
        "cylinder_detail_tris": cylinder_detail_tris,
        "remaining_tris": remaining_tris,
        "skipped_due_to_must_keep": skipped_due_to_must_keep,
    }
    _write_json(output_directory / "stage_2b_deleted_features_report.json", report)
    mesh_objects = _mesh_objects()
    _render_bucket_map(mesh_objects, bucket_triangles, output_directory / "stage_2b_deleted_features_map.png")
    return report


def _classify_unassigned_reduce_first(
    mesh_objects: list[bpy.types.Object],
    bucket_triangles: dict[str, dict[str, set[int]]],
    payload: dict[str, Any] | None,
) -> None:
    bounds = _bounds_from_report(payload)
    dense_cells = _high_density_cells(payload)
    for obj in mesh_objects:
        obj.data.calc_loop_triangles()
        assigned = set().union(*(bucket_triangles.get(obj.name, {}).get(bucket, set()) for bucket in BUCKETS))
        reduce_first = bucket_triangles.setdefault(obj.name, {bucket: set() for bucket in BUCKETS})["REDUCE_FIRST"]
        soft_keep = bucket_triangles[obj.name]["SOFT_KEEP"]
        for triangle in obj.data.loop_triangles:
            triangle_index = int(triangle.index)
            if triangle_index in assigned:
                continue
            if bounds is not None and _grid_key(_triangle_centroid_world(obj, triangle), bounds[0], bounds[1]) in dense_cells:
                reduce_first.add(triangle_index)
            else:
                soft_keep.add(triangle_index)


def _stage2c_bucket_controlled_decimate(
    mesh_objects: list[bpy.types.Object],
    bucket_triangles: dict[str, dict[str, set[int]]],
    protected_vertices: dict[str, set[int]],
    payload: dict[str, Any] | None,
    output_directory: Path,
    target: int,
    minimum_ratio: float,
    max_iterations: int,
) -> tuple[int, dict[str, Any]]:
    _classify_unassigned_reduce_first(mesh_objects, bucket_triangles, payload)
    input_tris = _count_scene_triangles(mesh_objects)
    bucket_report: dict[str, dict[str, int]] = {
        bucket: {"input_tris": _triangle_count_for_bucket(mesh_objects, bucket_triangles, bucket), "output_tris": 0}
        for bucket in BUCKETS
    }
    _render_bucket_map(mesh_objects, bucket_triangles, output_directory / "stage_2c_bucket_heatmap.png")
    must_keep_vertices = _bucket_vertices_by_object(mesh_objects, bucket_triangles, "MUST_KEEP")
    soft_keep_vertices = _bucket_vertices_by_object(mesh_objects, bucket_triangles, "SOFT_KEEP")
    reduce_first_vertices = _bucket_vertices_by_object(mesh_objects, bucket_triangles, "REDUCE_FIRST")
    delete_candidate_vertices = _bucket_vertices_by_object(mesh_objects, bucket_triangles, "DELETE_CANDIDATE")
    protected_stage_vertices = _merge_vertex_maps(protected_vertices, must_keep_vertices, soft_keep_vertices)
    target_stage_vertices = _subtract_vertex_map(
        _merge_vertex_maps(reduce_first_vertices, delete_candidate_vertices),
        protected_stage_vertices,
    )
    decimate_objects = [obj for obj in mesh_objects if target_stage_vertices.get(obj.name)]
    optimize_warnings: list[str] = []
    if decimate_objects:
        current, _, _, optimize_warnings = _optimize_objects(
            decimate_objects,
            mesh_objects,
            target,
            minimum_ratio,
            max_iterations,
            protected_vertices_by_object=protected_stage_vertices,
            target_vertices_by_object=target_stage_vertices,
        )
    else:
        current = input_tris
        optimize_warnings.append("Stage 2C skipped controlled decimate because no reduce-first target vertices were found.")
    mesh_objects = _mesh_objects()

    for bucket in BUCKETS:
        bucket_report[bucket]["output_tris"] = _triangle_count_for_bucket(mesh_objects, bucket_triangles, bucket)

    output_blend = output_directory / "stage_2c_bucket_decimate.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))
    _render_stage_map(mesh_objects, output_directory / "stage_2c_model_preview.png")
    report = {
        "stage": "2C_bucket_controlled_decimate",
        "input_tris": input_tris,
        "output_tris": _count_scene_triangles(mesh_objects),
        "target_tris": target,
        "buckets": bucket_report,
        "strategy": "target_reduce_first_and_delete_candidates_only",
        "heatmap_timing": "before_decimate",
        "target_vertices": _vertex_map_count(target_stage_vertices),
        "protected_vertices": _vertex_map_count(protected_stage_vertices),
        "decimated_objects": [obj.name for obj in decimate_objects],
        "warnings": optimize_warnings,
        "blend_file": str(output_blend),
    }
    _write_json(output_directory / "stage_2c_bucket_report.json", report)
    return int(report["output_tris"]), report


def _stage2d_local_fallback(
    mesh_objects: list[bpy.types.Object],
    bucket_triangles: dict[str, dict[str, set[int]]],
    output_directory: Path,
    target: int,
    minimum_ratio: float,
    max_iterations: int,
) -> tuple[int, dict[str, Any]]:
    input_tris = _count_scene_triangles(mesh_objects)
    current = input_tris
    passes: list[dict[str, Any]] = []
    pass_order = ("DELETE_CANDIDATE", "REDUCE_FIRST")
    retention_ratio = (target / input_tris) if input_tris else 1.0
    if retention_ratio <= 0.08:
        quality_floor_ratio = 0.35
    elif retention_ratio <= 0.15:
        quality_floor_ratio = 0.35
    elif retention_ratio <= 0.35:
        quality_floor_ratio = 0.35
    else:
        quality_floor_ratio = 0.30
    stage_protected_vertices = _merge_vertex_maps(
        _bucket_vertices_by_object(mesh_objects, bucket_triangles, "MUST_KEEP"),
        _bucket_vertices_by_object(mesh_objects, bucket_triangles, "SOFT_KEEP"),
    )
    for bucket in pass_order:
        if current <= target:
            break
        target_vertices = _subtract_vertex_map(
            _bucket_vertices_by_object(mesh_objects, bucket_triangles, bucket),
            stage_protected_vertices,
        )
        if not target_vertices:
            continue
        decimate_objects = [obj for obj in mesh_objects if target_vertices.get(obj.name)]
        before = current
        current, _, _, warnings = _optimize_objects(
            decimate_objects,
            mesh_objects,
            target,
            max(quality_floor_ratio, minimum_ratio),
            max_iterations,
            protected_vertices_by_object=stage_protected_vertices,
            target_vertices_by_object=target_vertices,
        )
        mesh_objects = _mesh_objects()
        passes.append({
            "bucket": bucket,
            "input_tris": before,
            "output_tris": current,
            "quality_floor_ratio": quality_floor_ratio,
            "target_vertices": _vertex_map_count(target_vertices),
            "protected_vertices": _vertex_map_count(stage_protected_vertices),
            "decimated_objects": [obj.name for obj in decimate_objects],
            "warnings": warnings,
        })

    output_blend = output_directory / "stage_2d_final.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))
    _render_stage_map(mesh_objects, output_directory / "stage_2d_model_preview.png")
    report = {
        "stage": "2D_local_fallback",
        "input_tris": input_tris,
        "output_tris": current,
        "target_tris": target,
        "passes": passes,
        "soft_keep_deferred": True,
        "quality_floor_ratio": quality_floor_ratio,
        "quality_floor_reason": "Stage 2D only decimates REDUCE_FIRST/DELETE_CANDIDATE and keeps a higher ratio for very tight targets.",
        "strict_target": False,
        "global_decimate_used": False,
        "blend_file": str(output_blend),
    }
    _write_json(output_directory / "stage_2d_report.json", report)
    return current, report


def _stage3_detail_suppression(
    mesh_objects: list[bpy.types.Object],
    bucket_triangles: dict[str, dict[str, set[int]]],
    output_directory: Path,
) -> tuple[int, dict[str, Any]]:
    input_tris = _count_scene_triangles(mesh_objects)
    _, scene_size, _ = _scene_bounds(mesh_objects)
    scene_diag = max(scene_size.length, 1.0)
    deleted_components = 0
    deleted_tris = 0
    dissolved_polygons = 0
    dissolved_delete_polygons = 0
    dissolved_reduce_polygons = 0
    skipped_components = 0
    object_reports: list[dict[str, Any]] = []

    for obj in mesh_objects:
        obj.data.calc_loop_triangles()
        must_keep = bucket_triangles.get(obj.name, {}).get("MUST_KEEP", set())
        soft_keep = bucket_triangles.get(obj.name, {}).get("SOFT_KEEP", set())
        reduce_first = set(bucket_triangles.get(obj.name, {}).get("REDUCE_FIRST", set()))
        delete_candidate = set(bucket_triangles.get(obj.name, {}).get("DELETE_CANDIDATE", set()))
        protected = must_keep | soft_keep
        safe_delete_polygons: set[int] = set()
        for component in _connected_triangle_components(obj):
            if not component <= delete_candidate:
                continue
            if component & protected:
                skipped_components += 1
                continue
            _, _, component_diag = _component_bounds(obj, component)
            area = sum(
                _triangle_area_world(obj, obj.data.loop_triangles[index])
                for index in component
                if index < len(obj.data.loop_triangles)
            )
            if len(component) <= 8 and component_diag <= scene_diag * 0.008 and area <= scene_diag * scene_diag * 0.000006:
                safe_delete_polygons.update(_polygon_indices_for_triangles(obj, component))

        if safe_delete_polygons:
            deleted_tris += sum(
                1 for triangle in obj.data.loop_triangles
                if int(triangle.polygon_index) in safe_delete_polygons
            )
            deleted_components += 1
            _delete_polygons(obj, safe_delete_polygons)
            obj.data.calc_loop_triangles()

        delete_dissolve_triangles = delete_candidate - protected
        reduce_dissolve_triangles = reduce_first - protected - delete_candidate
        delete_dissolve_polygons = _polygon_indices_for_triangles(obj, delete_dissolve_triangles)
        reduce_dissolve_polygons = _polygon_indices_for_triangles(obj, reduce_dissolve_triangles)
        if delete_dissolve_polygons:
            dissolved_delete_polygons += len(delete_dissolve_polygons)
            _limited_dissolve_polygons(obj, delete_dissolve_polygons, angle_limit=0.45)
            obj.data.calc_loop_triangles()
        if reduce_dissolve_polygons:
            dissolved_reduce_polygons += len(reduce_dissolve_polygons)
            _limited_dissolve_polygons(obj, reduce_dissolve_polygons, angle_limit=0.32)
            obj.data.calc_loop_triangles()
        dissolved_polygons = dissolved_delete_polygons + dissolved_reduce_polygons

        if safe_delete_polygons or delete_dissolve_polygons or reduce_dissolve_polygons:
            object_reports.append(
                {
                    "object_name": obj.name,
                    "deleted_polygons": len(safe_delete_polygons),
                    "dissolved_delete_polygons": len(delete_dissolve_polygons),
                    "dissolved_reduce_polygons": len(reduce_dissolve_polygons),
                    "dissolved_polygons": len(delete_dissolve_polygons) + len(reduce_dissolve_polygons),
                }
            )

    mesh_objects = _mesh_objects()
    output_tris = _count_scene_triangles(mesh_objects)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_directory / "stage_3_detail_suppression.blend"))
    _render_stage_map(mesh_objects, output_directory / "stage_3_model_preview.png")
    report = {
        "stage": "3_detail_suppression",
        "input_tris": input_tris,
        "output_tris": output_tris,
        "deleted_components": deleted_components,
        "deleted_tris_estimate": deleted_tris,
        "dissolved_polygons": dissolved_polygons,
        "dissolved_delete_polygons": dissolved_delete_polygons,
        "dissolved_reduce_polygons": dissolved_reduce_polygons,
        "skipped_components": skipped_components,
        "objects": object_reports,
        "strategy": "generic_candidate_delete_and_two_strength_limited_dissolve",
        "blend_file": str(output_directory / "stage_3_detail_suppression.blend"),
    }
    _write_json(output_directory / "stage_3_report.json", report)
    return output_tris, report


def _triangle_budget_plan(
    payload: dict[str, Any] | None,
    current_triangles: int,
    target_triangles: int,
) -> tuple[dict[str, Any], list[str]]:
    if payload is None:
        return {
            "must_keep": 0,
            "soft_keep": 0,
            "reduce_first": 0,
            "delete_candidate": 0,
            "retention_ratio": 0.0,
            "requires_aggressive": True,
        }, ["Budget Planner: no candidate report; aggressive fallback may be required."]

    retention_ratio = (target_triangles / current_triangles) if current_triangles else 1.0
    classes = {
        "MUST_KEEP": 0,
        "SOFT_KEEP": 0,
        "REDUCE_FIRST": 0,
        "DELETE_CANDIDATE": 0,
    }
    for candidate in payload.get("optimization_candidates", []):
        action = str(candidate.get("recommended_action", ""))
        region_type = str(candidate.get("region_type", ""))
        triangles = int(candidate.get("triangle_count", 0))
        surface_area = float(candidate.get("surface_area", 0.0))
        density = float(candidate.get("density", 0.0))
        silhouette_score = float(candidate.get("silhouette_score", 0.0))

        if silhouette_score >= 2.0 or region_type == "silhouette_region":
            bucket = "MUST_KEEP"
        elif triangles <= 8 and silhouette_score <= 0.0:
            bucket = "DELETE_CANDIDATE"
        elif surface_area <= 1e-5 and silhouette_score <= 0.0:
            bucket = "DELETE_CANDIDATE"
        elif action in TARGET_ACTIONS:
            bucket = "REDUCE_FIRST"
        elif action == "inspect" and silhouette_score <= 0.0 and density > 0.0:
            bucket = "REDUCE_FIRST"
        else:
            bucket = "SOFT_KEEP"

        if bucket == "SOFT_KEEP" and retention_ratio <= 0.10:
            bucket = "REDUCE_FIRST"
        classes[bucket] += max(triangles, 0)

    plan = {
        "must_keep": classes["MUST_KEEP"],
        "soft_keep": classes["SOFT_KEEP"],
        "reduce_first": classes["REDUCE_FIRST"],
        "delete_candidate": classes["DELETE_CANDIDATE"],
        "retention_ratio": retention_ratio,
        "requires_aggressive": retention_ratio <= 0.35,
    }
    warnings = [
        "Budget Planner: "
        f"target keeps {retention_ratio * 100.0:.1f}% of current triangles.",
        "Budget classes: "
        f"MUST_KEEP {classes['MUST_KEEP']:,} tris, "
        f"SOFT_KEEP {classes['SOFT_KEEP']:,} tris, "
        f"REDUCE_FIRST {classes['REDUCE_FIRST']:,} tris, "
        f"DELETE_CANDIDATE {classes['DELETE_CANDIDATE']:,} tris.",
    ]
    if retention_ratio <= 0.10:
        warnings.append(
            "Budget Planner: target is extremely tight; high curvature without silhouette protection is no longer treated as MUST_KEEP."
        )
    elif retention_ratio <= 0.35:
        warnings.append(
            "Budget Planner: conservative reduction may not be enough; aggressive reduce-first is allowed if needed."
        )
    return plan, warnings


def _candidate_report_path(source: Path) -> Path:
    return source.parent / "geometry_reports" / "geometry_report.json"


def _candidate_report(source: Path) -> tuple[dict[str, Any] | None, list[str]]:
    report_path = _candidate_report_path(source)
    if not report_path.exists():
        return None, ["Optimization candidates were not found; using legacy global optimization."]
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"Optimization candidates could not be read: {exc}"]

    report_source = Path(str(payload.get("source_file", "")))
    try:
        if report_source.resolve() != source.resolve():
            return None, [
                "Optimization candidates were for a different model; using legacy global optimization."
            ]
    except OSError:
        return None, ["Optimization candidate source could not be verified."]
    return payload, []


def _protected_triangle_indices(payload: dict[str, Any] | None) -> tuple[dict[str, set[int]], list[str]]:
    if payload is None:
        return {}, []
    protected: dict[str, set[int]] = {}
    for triangle in payload.get("silhouette", {}).get("top_triangles", []):
        if int(triangle.get("silhouette_hits", 0)) < 2:
            continue
        object_name = str(triangle.get("object_name", ""))
        if not object_name:
            continue
        protected.setdefault(object_name, set()).add(int(triangle.get("triangle_index", 0)))
    if not protected:
        return {}, ["No protected triangles were found in optimization candidates."]
    total = sum(len(items) for items in protected.values())
    return protected, [
        f"Candidate-aware optimization protected {total} silhouette triangles across "
        f"{len(protected)} object(s)."
    ]


def _protected_vertices_by_object(
    mesh_objects: list[bpy.types.Object],
    protected_triangles: dict[str, set[int]],
) -> tuple[dict[str, set[int]], list[str]]:
    protected_vertices: dict[str, set[int]] = {}
    for obj in mesh_objects:
        triangle_indices = protected_triangles.get(obj.name)
        if not triangle_indices:
            continue
        obj.data.calc_loop_triangles()
        vertices: set[int] = set()
        for triangle in obj.data.loop_triangles:
            if triangle.index in triangle_indices:
                vertices.update(int(vertex) for vertex in triangle.vertices)
        if vertices:
            protected_vertices[obj.name] = vertices
    if not protected_vertices:
        return {}, ["Protected triangle ids did not match current mesh data."]
    total_vertices = sum(len(items) for items in protected_vertices.values())
    return protected_vertices, [
        f"Candidate-aware optimization protected {total_vertices} vertices with vertex groups."
    ]


def _candidate_cells(payload: dict[str, Any] | None) -> tuple[set[tuple[int, int, int]], list[str]]:
    if payload is None:
        return set(), []
    cells: set[tuple[int, int, int]] = set()
    for candidate in payload.get("optimization_candidates", []):
        if candidate.get("recommended_action") not in TARGET_ACTIONS:
            continue
        region_id = str(candidate.get("region_id", ""))
        if not region_id.startswith("cell_"):
            continue
        parts = region_id.split("_")
        if len(parts) != 4:
            continue
        try:
            cells.add((int(parts[1]), int(parts[2]), int(parts[3])))
        except ValueError:
            continue
    if not cells:
        return set(), ["No candidate target cells were found; decimating non-protected regions."]
    return cells, [f"Candidate-aware optimization targets {len(cells)} dense cleanup cell(s)."]


def _bounds_from_report(payload: dict[str, Any] | None) -> tuple[Vector, Vector] | None:
    if payload is None:
        return None
    box = payload.get("overall", {}).get("bounding_box", {})
    try:
        return (
            Vector((float(box["min_x"]), float(box["min_y"]), float(box["min_z"]))),
            Vector((float(box["max_x"]), float(box["max_y"]), float(box["max_z"]))),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _grid_key(point: Vector, bounds_min: Vector, bounds_max: Vector) -> tuple[int, int, int]:
    size = bounds_max - bounds_min
    key: list[int] = []
    for axis in range(3):
        extent = max(size[axis], 1e-9)
        value = int(((point[axis] - bounds_min[axis]) / extent) * GRID_DIVISIONS)
        key.append(max(0, min(GRID_DIVISIONS - 1, value)))
    return key[0], key[1], key[2]


def _candidate_target_vertices_by_object(
    mesh_objects: list[bpy.types.Object],
    candidate_cells: set[tuple[int, int, int]],
    bounds: tuple[Vector, Vector] | None,
    protected_vertices: dict[str, set[int]],
) -> tuple[dict[str, set[int]], list[str]]:
    if not candidate_cells or bounds is None:
        return {}, []
    bounds_min, bounds_max = bounds
    target_vertices: dict[str, set[int]] = {}
    for obj in mesh_objects:
        obj.data.calc_loop_triangles()
        protected = protected_vertices.get(obj.name, set())
        selected: set[int] = set()
        for triangle in obj.data.loop_triangles:
            vertices = [obj.matrix_world @ obj.data.vertices[index].co for index in triangle.vertices]
            centroid = (vertices[0] + vertices[1] + vertices[2]) / 3.0
            if _grid_key(centroid, bounds_min, bounds_max) not in candidate_cells:
                continue
            selected.update(int(vertex) for vertex in triangle.vertices if int(vertex) not in protected)
        if selected:
            target_vertices[obj.name] = selected
    if not target_vertices:
        return {}, ["Candidate target cells did not match current mesh vertices."]
    total = sum(len(items) for items in target_vertices.values())
    return target_vertices, [
        f"Candidate-aware optimization targets {total} vertices from cleanup candidates."
    ]


def _score(triangle_count: int, warning_triangles: int, critical_triangles: int) -> int:
    if triangle_count > critical_triangles:
        return 40
    if triangle_count > warning_triangles:
        return 65
    if triangle_count >= 5000:
        return 85
    return 95


def _rating(score: int) -> str:
    if score < 50:
        return "Critical"
    if score < 75:
        return "Warning"
    if score < 90:
        return "Good"
    return "Excellent"


def _configure_render(preview_image: Path) -> None:
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_WORKBENCH"
    except TypeError:
        try:
            scene.render.engine = "BLENDER_EEVEE_NEXT"
        except TypeError:
            scene.render.engine = "BLENDER_EEVEE"

    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.film_transparent = False
    scene.world.color = (0.78, 0.80, 0.84)
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(preview_image)


def _scene_bounds(mesh_objects: list[bpy.types.Object]) -> tuple[Vector, Vector, float]:
    points = [obj.matrix_world @ Vector(corner) for obj in mesh_objects for corner in obj.bound_box]
    if not points:
        return Vector((0.0, 0.0, 0.0)), Vector((1.0, 1.0, 1.0)), 1.0
    minimum = Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points)))
    maximum = Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points)))
    center = (minimum + maximum) / 2.0
    size = maximum - minimum
    diagonal = max(size.length, 1.0)
    return center, size, diagonal


def _look_at(obj: bpy.types.Object, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _setup_camera_and_light(mesh_objects: list[bpy.types.Object]) -> None:
    for obj in list(bpy.context.scene.objects):
        if obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(obj, do_unlink=True)

    center, size, diagonal = _scene_bounds(mesh_objects)
    camera_data = bpy.data.cameras.new("AssetForge_Preview_Camera")
    camera = bpy.data.objects.new("AssetForge_Preview_Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = center + Vector((diagonal * 0.9, -diagonal * 1.8, diagonal * 0.8))
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = max(size.x * 0.82 + size.z * 0.55, size.y * 0.45 + size.z * 0.9, 1.0) * 1.18
    _look_at(camera, center)
    bpy.context.scene.camera = camera

    light_data = bpy.data.lights.new("AssetForge_Preview_Light", type="AREA")
    light = bpy.data.objects.new("AssetForge_Preview_Light", light_data)
    bpy.context.collection.objects.link(light)
    light.location = center + Vector((diagonal * 0.5, -diagonal * 0.7, diagonal * 1.4))
    light_data.energy = 500
    light_data.size = max(diagonal, 1.0)
    _look_at(light, center)


def _generate_item(args: argparse.Namespace, target: int, output_directory: Path) -> dict[str, Any]:
    source = Path(args.blend_file)
    preview_blend = output_directory / f"preview_{target}.blend"
    preview_image = output_directory / f"preview_{target}.png"
    warnings: list[str] = []
    errors: list[str] = []

    shutil.copy2(source, preview_blend)
    bpy.ops.wm.open_mainfile(filepath=str(preview_blend))
    mesh_objects = _mesh_objects()
    body, wheels, classify_warnings, classify_errors = _classify_vehicle(mesh_objects)
    warnings.extend(classify_warnings)
    errors.extend(classify_errors)

    original_triangles = _count_scene_triangles(mesh_objects)
    actual_triangles = original_triangles
    if body is None or errors:
        errors.append("Preview optimization skipped because the vehicle structure was not usable.")
    elif original_triangles <= target:
        warnings.append("Model already satisfies target triangle limit.")
        _setup_camera_and_light(mesh_objects)
        _configure_render(preview_image)
        bpy.ops.render.render(write_still=False)
        bpy.data.images["Render Result"].save_render(filepath=str(preview_image))
    else:
        _apply_transforms(mesh_objects)
        decimate_objects = [body] if args.decimate_body_only else mesh_objects
        candidate_payload, report_warnings = _candidate_report(source)
        warnings.extend(report_warnings)
        budget_plan, budget_warnings = _triangle_budget_plan(
            candidate_payload,
            original_triangles,
            target,
        )
        warnings.extend(budget_warnings)
        protected_triangles, protected_warnings = _protected_triangle_indices(candidate_payload)
        warnings.extend(protected_warnings)
        protected_vertices, vertex_warnings = _protected_vertices_by_object(
            mesh_objects,
            protected_triangles,
        )
        warnings.extend(vertex_warnings)
        cells, cell_warnings = _candidate_cells(candidate_payload)
        warnings.extend(cell_warnings)
        target_vertices, target_warnings = _candidate_target_vertices_by_object(
            mesh_objects,
            cells,
            _bounds_from_report(candidate_payload),
            protected_vertices,
        )
        warnings.extend(target_warnings)
        actual_triangles, _, _, optimize_warnings = _optimize_objects(
            decimate_objects=decimate_objects,
            mesh_objects=mesh_objects,
            target_triangles=target,
            minimum_ratio=args.minimum_ratio,
            max_iterations=args.max_iterations,
            protected_vertices_by_object=protected_vertices,
            target_vertices_by_object=target_vertices,
        )
        warnings.append(
            f"Stage 1 Conservative Importance-Aware Reduce: {original_triangles:,} -> "
            f"{actual_triangles:,} tris."
        )
        warnings.extend(optimize_warnings)
        if (
            actual_triangles > target
            and protected_vertices
            and args.pipeline_stage >= 2
        ):
            warnings.append(
                "Stage 1 did not reach target; entering Stage 2 Aggressive Reduce."
            )
            bpy.ops.wm.open_mainfile(filepath=str(preview_blend))
            mesh_objects = _mesh_objects()
            body, _, _, reload_errors = _classify_vehicle(mesh_objects)
            if body is None or reload_errors:
                errors.extend(reload_errors or ["Aggressive reduction could not reload vehicle structure."])
            else:
                _apply_transforms(mesh_objects)
                stage2_input = _count_scene_triangles(mesh_objects)
                bucket_triangles, expanded_protected_vertices, stage2a_report = _stage2a_structural_protection_expansion(
                    mesh_objects,
                    candidate_payload,
                    output_directory,
                    stage2_input,
                    ring_count=args.protection_ring_count,
                )
                mesh_objects = _mesh_objects()
                stage2b_report = _stage2b_tiny_feature_delete(
                    mesh_objects,
                    bucket_triangles,
                    candidate_payload,
                    output_directory,
                )
                mesh_objects = _mesh_objects()
                stage3_report: dict[str, Any] | None = None
                if args.pipeline_stage >= 3:
                    stage3_triangles, stage3_report = _stage3_detail_suppression(
                        mesh_objects,
                        bucket_triangles,
                        output_directory,
                    )
                    warnings.append(
                        f"Stage 3 Detail Suppression: "
                        f"{stage3_report['input_tris']:,} -> {stage3_report['output_tris']:,} tris, "
                        f"dissolved {stage3_report['dissolved_polygons']:,} polygons."
                    )
                    mesh_objects = _mesh_objects()
                stage2c_triangles, stage2c_report = _stage2c_bucket_controlled_decimate(
                    mesh_objects,
                    bucket_triangles,
                    expanded_protected_vertices,
                    candidate_payload,
                    output_directory,
                    target,
                    args.minimum_ratio,
                    args.max_iterations,
                )
                mesh_objects = _mesh_objects()
                if stage2c_triangles > target:
                    aggressive_triangles, stage2d_report = _stage2d_local_fallback(
                        mesh_objects,
                        bucket_triangles,
                        output_directory,
                        target,
                        args.minimum_ratio,
                        args.max_iterations,
                    )
                else:
                    aggressive_triangles = stage2c_triangles
                    stage2d_report = {
                        "stage": "2D_local_fallback",
                        "input_tris": stage2c_triangles,
                        "output_tris": stage2c_triangles,
                        "target_tris": target,
                        "passes": [],
                        "skipped": "Stage 2C reached target.",
                        "strict_target": False,
                        "global_decimate_used": False,
                    }
                    _write_json(output_directory / "stage_2d_report.json", stage2d_report)
                    _render_stage_map(mesh_objects, output_directory / "stage_2d_model_preview.png")
                stage2_report = {
                    "stage": "2_staged_aggressive_optimizer",
                    "input_tris": stage2_input,
                    "output_tris": aggressive_triangles,
                    "target_tris": target,
                    "substages": {
                        "2A": stage2a_report,
                        "2B": stage2b_report,
                        "3": stage3_report,
                        "2C": stage2c_report,
                        "2D": stage2d_report,
                    },
                }
                _write_json(output_directory / "stage_2_report.json", stage2_report)
                warnings.append(
                    f"Stage 2A Structural Protection Expansion: "
                    f"{stage2a_report['base_silhouette_tris']:,} base silhouette tris -> "
                    f"{stage2a_report['expanded_must_keep_tris']:,} MUST_KEEP + "
                    f"{stage2a_report['expanded_soft_keep_tris']:,} SOFT_KEEP tris."
                )
                warnings.append(
                    f"Stage 2B Detail Candidate Detection: marked "
                    f"{stage2b_report['marked_delete_candidate_tris']:,} delete-candidate tris and "
                    f"{stage2b_report['attached_detail_reduce_tris']:,} reduce-first detail tris."
                )
                warnings.append(
                    f"Stage 2C Bucket-Based Controlled Decimate: "
                    f"{stage2c_report['input_tris']:,} -> {stage2c_report['output_tris']:,} tris."
                )
                warnings.append(
                    f"Stage 2D Local Fallback: "
                    f"{stage2d_report['input_tris']:,} -> {stage2d_report['output_tris']:,} tris."
                )
                warnings.append(
                    f"Stage {max(2, args.pipeline_stage)} pipeline result: {original_triangles:,} -> "
                    f"{aggressive_triangles:,} tris."
                )
                if aggressive_triangles > target:
                    warnings.append(
                        "Stage 2 stopped above target to preserve protected and soft-keep structure. "
                        "Reaching this target requires dedicated low-poly reconstruction rather than more fallback decimate."
                    )
                actual_triangles = aggressive_triangles
        elif actual_triangles > target:
            if args.pipeline_stage < 2:
                warnings.append(
                    "Stage 1 did not reach target. Stage 2 Aggressive Reduce was not run because the selected pipeline stage is Conservative only."
                )
            else:
                warnings.append(
                    "Stage 1 did not reach target, but Budget Planner kept aggressive mode disabled for this target."
                )
        mesh_objects = _mesh_objects()
        _setup_camera_and_light(mesh_objects)
        _configure_render(preview_image)
        bpy.ops.render.render(write_still=False)
        bpy.data.images["Render Result"].save_render(filepath=str(preview_image))

    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(preview_blend))
    reduction = 0.0
    if original_triangles > 0:
        reduction = round(((original_triangles - actual_triangles) / original_triangles) * 100.0, 2)
    score = _score(actual_triangles, args.warning_triangles, args.critical_triangles)
    return {
        "target_triangles": target,
        "actual_triangles": actual_triangles,
        "reduction_percent": reduction,
        "compatibility_score": score,
        "rating": _rating(score),
        "preview_blend_path": str(preview_blend),
        "preview_image_path": str(preview_image),
        "warnings": warnings,
        "errors": errors,
    }


def generate(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.blend_file)
    output_directory = Path(args.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    errors: list[str] = []

    if not source.exists():
        errors.append(f"Blend file does not exist: {source}")
        original_triangles = 0
        items: list[dict[str, Any]] = []
    else:
        bpy.ops.wm.open_mainfile(filepath=str(source))
        original_triangles = _count_scene_triangles(_mesh_objects())
        items = [_generate_item(args, args.target_triangles, output_directory)]

    return {
        "source_blend_file": str(source),
        "output_directory": str(output_directory),
        "original_triangle_count": original_triangles,
        "profile_id": args.profile_id,
        "items": items,
        "warnings": warnings,
        "errors": errors,
    }


def _parse_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate real AssetForge optimization previews.")
    parser.add_argument("--blend-file", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--target-triangles", type=int, required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--minimum-ratio", type=float, required=True)
    parser.add_argument("--max-iterations", type=int, required=True)
    parser.add_argument("--decimate-body-only", type=_parse_bool, required=True)
    parser.add_argument("--warning-triangles", type=int, required=True)
    parser.add_argument("--critical-triangles", type=int, required=True)
    parser.add_argument("--pipeline-stage", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--protection-ring-count", type=int, choices=(1, 2), default=1)
    return parser.parse_args(argv)


def main() -> int:
    argv = sys.argv
    script_args = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    args = parse_args(script_args)
    report = generate(args)
    Path(args.output_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
