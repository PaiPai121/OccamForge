from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector


PLANAR_NORMAL_DOT = math.cos(math.radians(5.0))
LOW_CURVATURE_DEGREES = 15.0
MEDIUM_CURVATURE_DEGREES = 45.0
GRID_DIVISIONS = 12
SILHOUETTE_RESOLUTION = 96
SILHOUETTE_PROTECTED_HITS = 2
MIN_CANDIDATE_TRIANGLES = 25
SILHOUETTE_VIEWS: tuple[tuple[str, Vector], ...] = (
    ("Front", Vector((0.0, -1.0, 0.0))),
    ("Back", Vector((0.0, 1.0, 0.0))),
    ("Left", Vector((-1.0, 0.0, 0.0))),
    ("Right", Vector((1.0, 0.0, 0.0))),
    ("Top", Vector((0.0, 0.0, 1.0))),
    ("45 Degree", Vector((1.0, -1.0, 0.45))),
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
        raise ValueError(f"Unsupported geometry source type: {source_file.suffix}")


def _mesh_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def _triangle_area(a: Vector, b: Vector, c: Vector) -> float:
    return ((b - a).cross(c - a).length) * 0.5


def _face_normal(mesh: bpy.types.Mesh, obj: bpy.types.Object, polygon: bpy.types.MeshPolygon) -> Vector:
    normal = obj.matrix_world.to_3x3() @ polygon.normal
    if normal.length == 0:
        return Vector((0.0, 0.0, 1.0))
    normal.normalize()
    return normal


def _collect_bounds(mesh_objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    mins = Vector((math.inf, math.inf, math.inf))
    maxs = Vector((-math.inf, -math.inf, -math.inf))
    for obj in mesh_objects:
        for vertex in obj.data.vertices:
            world = obj.matrix_world @ vertex.co
            mins.x = min(mins.x, world.x)
            mins.y = min(mins.y, world.y)
            mins.z = min(mins.z, world.z)
            maxs.x = max(maxs.x, world.x)
            maxs.y = max(maxs.y, world.y)
            maxs.z = max(maxs.z, world.z)
    if math.isinf(mins.x):
        return Vector((0.0, 0.0, 0.0)), Vector((0.0, 0.0, 0.0))
    return mins, maxs


def _face_triangle_count(mesh: bpy.types.Mesh, polygon_index: int) -> int:
    mesh.calc_loop_triangles()
    return sum(1 for tri in mesh.loop_triangles if tri.polygon_index == polygon_index)


def _build_face_adjacency(mesh: bpy.types.Mesh) -> dict[int, set[int]]:
    edge_to_faces: dict[tuple[int, int], list[int]] = defaultdict(list)
    for polygon in mesh.polygons:
        vertices = list(polygon.vertices)
        for index, first in enumerate(vertices):
            second = vertices[(index + 1) % len(vertices)]
            edge_to_faces[tuple(sorted((first, second)))].append(polygon.index)

    adjacency: dict[int, set[int]] = {polygon.index: set() for polygon in mesh.polygons}
    for faces in edge_to_faces.values():
        if len(faces) < 2:
            continue
        for face in faces:
            adjacency[face].update(other for other in faces if other != face)
    return adjacency


def _planar_regions_for_object(obj: bpy.types.Object) -> list[list[int]]:
    mesh = obj.data
    adjacency = _build_face_adjacency(mesh)
    normals = {
        polygon.index: _face_normal(mesh, obj, polygon)
        for polygon in mesh.polygons
    }
    visited: set[int] = set()
    regions: list[list[int]] = []
    for polygon in mesh.polygons:
        if polygon.index in visited:
            continue
        region: list[int] = []
        queue: deque[int] = deque([polygon.index])
        visited.add(polygon.index)
        seed_normal = normals[polygon.index]
        while queue:
            current = queue.popleft()
            region.append(current)
            for neighbor in adjacency[current]:
                if neighbor in visited:
                    continue
                if seed_normal.dot(normals[neighbor]) >= PLANAR_NORMAL_DOT:
                    visited.add(neighbor)
                    queue.append(neighbor)
        regions.append(region)
    return regions


def _curvature_counts_for_object(obj: bpy.types.Object) -> dict[str, int]:
    mesh = obj.data
    mesh.calc_loop_triangles()
    adjacency = _build_face_adjacency(mesh)
    normals = {
        polygon.index: _face_normal(mesh, obj, polygon)
        for polygon in mesh.polygons
    }
    triangles_by_face: dict[int, int] = defaultdict(int)
    for triangle in mesh.loop_triangles:
        triangles_by_face[triangle.polygon_index] += 1

    counts = {"Low Curvature": 0, "Medium Curvature": 0, "High Curvature": 0}
    for polygon in mesh.polygons:
        angles: list[float] = []
        for neighbor in adjacency[polygon.index]:
            dot = max(-1.0, min(1.0, normals[polygon.index].dot(normals[neighbor])))
            angles.append(math.degrees(math.acos(dot)))
        curvature = max(angles) if angles else 0.0
        triangle_count = triangles_by_face[polygon.index]
        if curvature < LOW_CURVATURE_DEGREES:
            counts["Low Curvature"] += triangle_count
        elif curvature < MEDIUM_CURVATURE_DEGREES:
            counts["Medium Curvature"] += triangle_count
        else:
            counts["High Curvature"] += triangle_count
    return counts


def _world_triangle_vertices(
    obj: bpy.types.Object,
    triangle: bpy.types.MeshLoopTriangle,
) -> tuple[Vector, Vector, Vector]:
    vertices = obj.data.vertices
    a, b, c = triangle.vertices
    return (
        obj.matrix_world @ vertices[a].co,
        obj.matrix_world @ vertices[b].co,
        obj.matrix_world @ vertices[c].co,
    )


def _view_basis(direction: Vector) -> tuple[Vector, Vector, Vector]:
    view = direction.normalized()
    up_hint = Vector((0.0, 0.0, 1.0))
    if abs(view.dot(up_hint)) > 0.95:
        up_hint = Vector((0.0, 1.0, 0.0))
    right = up_hint.cross(view)
    if right.length == 0:
        right = Vector((1.0, 0.0, 0.0))
    right.normalize()
    up = view.cross(right)
    up.normalize()
    return right, up, view


def _point_in_projected_triangle(
    point: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> bool:
    px, py = point
    ax, ay = a
    bx, by = b
    cx, cy = c
    denominator = ((by - cy) * (ax - cx)) + ((cx - bx) * (ay - cy))
    if abs(denominator) < 1e-12:
        return False
    alpha = (((by - cy) * (px - cx)) + ((cx - bx) * (py - cy))) / denominator
    beta = (((cy - ay) * (px - cx)) + ((ax - cx) * (py - cy))) / denominator
    gamma = 1.0 - alpha - beta
    return alpha >= -1e-6 and beta >= -1e-6 and gamma >= -1e-6


def _collect_world_triangles(
    mesh_objects: list[bpy.types.Object],
) -> list[dict[str, Any]]:
    triangles: list[dict[str, Any]] = []
    for obj in mesh_objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        for triangle in mesh.loop_triangles:
            a, b, c = _world_triangle_vertices(obj, triangle)
            centroid = (a + b + c) / 3.0
            triangles.append(
                {
                    "key": (obj.name, triangle.index),
                    "object_name": obj.name,
                    "triangle_index": triangle.index,
                    "vertices": (a, b, c),
                    "centroid": centroid,
                }
            )
    return triangles


def _projected_bounds(
    triangles: list[dict[str, Any]],
    right: Vector,
    up: Vector,
) -> tuple[float, float, float, float]:
    min_u = math.inf
    max_u = -math.inf
    min_v = math.inf
    max_v = -math.inf
    for triangle in triangles:
        for vertex in triangle["vertices"]:
            projected_u = vertex.dot(right)
            projected_v = vertex.dot(up)
            min_u = min(min_u, projected_u)
            max_u = max(max_u, projected_u)
            min_v = min(min_v, projected_v)
            max_v = max(max_v, projected_v)
    if math.isinf(min_u):
        return 0.0, 1.0, 0.0, 1.0
    if abs(max_u - min_u) < 1e-9:
        max_u = min_u + 1.0
    if abs(max_v - min_v) < 1e-9:
        max_v = min_v + 1.0
    return min_u, max_u, min_v, max_v


def _pixel_range(values: list[float], minimum: float, maximum: float, resolution: int) -> range:
    scale = (resolution - 1) / max(maximum - minimum, 1e-9)
    low = max(0, min(resolution - 1, int(math.floor((min(values) - minimum) * scale))))
    high = max(0, min(resolution - 1, int(math.ceil((max(values) - minimum) * scale))))
    return range(low, high + 1)


def _silhouette_hits_for_view(
    triangles: list[dict[str, Any]],
    direction: Vector,
    resolution: int,
) -> tuple[dict[tuple[str, int], int], int]:
    right, up, view = _view_basis(direction)
    min_u, max_u, min_v, max_v = _projected_bounds(triangles, right, up)
    scale_u = (resolution - 1) / max(max_u - min_u, 1e-9)
    scale_v = (resolution - 1) / max(max_v - min_v, 1e-9)
    occupied: dict[tuple[int, int], tuple[float, tuple[str, int]]] = {}

    for triangle in triangles:
        projected = [
            (vertex.dot(right), vertex.dot(up), vertex.dot(view))
            for vertex in triangle["vertices"]
        ]
        pixel_points = [
            ((u - min_u) * scale_u, (v - min_v) * scale_v)
            for u, v, _depth in projected
        ]
        depth = sum(item[2] for item in projected) / 3.0
        for pixel_x in _pixel_range([item[0] for item in projected], min_u, max_u, resolution):
            for pixel_y in _pixel_range([item[1] for item in projected], min_v, max_v, resolution):
                center = (pixel_x + 0.5, pixel_y + 0.5)
                if not _point_in_projected_triangle(center, *pixel_points):
                    continue
                key = (pixel_x, pixel_y)
                current = occupied.get(key)
                if current is None or depth > current[0]:
                    occupied[key] = (depth, triangle["key"])

    outline_pixels: set[tuple[int, int]] = set()
    for pixel in occupied:
        x, y = pixel
        neighbors = ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1))
        if any(neighbor not in occupied for neighbor in neighbors):
            outline_pixels.add(pixel)

    hits: dict[tuple[str, int], int] = defaultdict(int)
    for pixel in outline_pixels:
        hits[occupied[pixel][1]] = 1
    return hits, len(hits)


def _silhouette_analysis(
    mesh_objects: list[bpy.types.Object],
    bounds_min: Vector,
    bounds_max: Vector,
) -> dict[str, Any]:
    triangles = _collect_world_triangles(mesh_objects)
    hit_counts: dict[tuple[str, int], int] = defaultdict(int)
    view_stats: list[dict[str, Any]] = []
    for name, direction in SILHOUETTE_VIEWS:
        view_hits, outline_count = _silhouette_hits_for_view(
            triangles,
            direction,
            SILHOUETTE_RESOLUTION,
        )
        for key in view_hits:
            hit_counts[key] += 1
        view_stats.append({"name": name, "outline_triangle_count": outline_count})

    triangle_lookup = {triangle["key"]: triangle for triangle in triangles}
    protected_keys = {
        key for key, count in hit_counts.items() if count >= SILHOUETTE_PROTECTED_HITS
    }
    region_stats: dict[tuple[str, tuple[int, int, int]], list[int]] = defaultdict(list)
    for key in protected_keys:
        triangle = triangle_lookup.get(key)
        if not triangle:
            continue
        grid = _grid_key(triangle["centroid"], bounds_min, bounds_max)
        region_stats[(triangle["object_name"], grid)].append(hit_counts[key])

    protected_regions = sorted(
        (
            {
                "region_id": f"silhouette_{object_name}_{grid[0]}_{grid[1]}_{grid[2]}",
                "object_name": object_name,
                "triangle_count": len(hits),
                "max_hits": max(hits),
                "average_hits": sum(hits) / len(hits),
                "recommended_action": "protect_candidate",
            }
            for (object_name, grid), hits in region_stats.items()
            if hits
        ),
        key=lambda item: (item["max_hits"], item["triangle_count"]),
        reverse=True,
    )[:20]
    top_triangles = sorted(
        (
            {
                "object_name": key[0],
                "triangle_index": key[1],
                "silhouette_hits": count,
            }
            for key, count in hit_counts.items()
        ),
        key=lambda item: item["silhouette_hits"],
        reverse=True,
    )[:2000]
    total_triangles = len(triangles)
    protected_count = len(protected_keys)
    return {
        "view_count": len(SILHOUETTE_VIEWS),
        "total_outline_triangles": len(hit_counts),
        "protected_triangle_count": protected_count,
        "protected_triangle_percentage": (
            protected_count / total_triangles * 100.0
        ) if total_triangles else 0.0,
        "max_hits": max(hit_counts.values()) if hit_counts else 0,
        "views": view_stats,
        "top_triangles": top_triangles,
        "protected_regions": protected_regions,
    }


def _candidate_confidence(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 3)


def _optimization_candidates(
    dense_regions: list[dict[str, Any]],
    silhouette: dict[str, Any],
    curvature_counts: dict[str, int],
    total_triangles: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    protected_region_ids: set[str] = set()
    for region in silhouette.get("protected_regions", []):
        protected_region_ids.add(str(region.get("region_id", "")))
        max_hits = float(region.get("max_hits", 0))
        average_hits = float(region.get("average_hits", 0.0))
        candidates.append(
            {
                "region_id": str(region.get("region_id", "")),
                "region_type": "silhouette_region",
                "recommended_action": "protect_candidate",
                "triangle_count": int(region.get("triangle_count", 0)),
                "surface_area": 0.0,
                "density": 0.0,
                "curvature": 0.0,
                "silhouette_score": max_hits,
                "confidence": _candidate_confidence((average_hits / max(len(SILHOUETTE_VIEWS), 1)) + 0.45),
                "rationale": "Visible on the model outline from multiple sampled views.",
            }
        )

    low_curvature = curvature_counts.get("Low Curvature", 0)
    low_curvature_ratio = (low_curvature / total_triangles) if total_triangles else 0.0
    high_curvature = curvature_counts.get("High Curvature", 0)
    high_curvature_ratio = (high_curvature / total_triangles) if total_triangles else 0.0

    for index, region in enumerate(dense_regions):
        triangle_count = int(region.get("triangle_count", 0))
        if triangle_count < MIN_CANDIDATE_TRIANGLES:
            continue
        density = float(region.get("density", 0.0))
        surface_area = float(region.get("surface_area", 0.0))
        region_id = str(region.get("region_id", ""))
        if index < 8 and high_curvature_ratio < 0.65:
            candidates.append(
                {
                    "region_id": region_id,
                    "region_type": "dense_low_curvature_region",
                    "recommended_action": "decimate_candidate",
                    "triangle_count": triangle_count,
                    "surface_area": surface_area,
                    "density": density,
                    "curvature": high_curvature_ratio,
                    "silhouette_score": 0.0,
                    "confidence": _candidate_confidence(0.55 + min(index, 8) * -0.03),
                    "rationale": "High triangle density with no silhouette protection marker.",
                }
            )
        elif low_curvature_ratio >= 0.10:
            candidates.append(
                {
                    "region_id": region_id,
                    "region_type": "flat_or_low_curvature_dense_region",
                    "recommended_action": "limited_dissolve_candidate",
                    "triangle_count": triangle_count,
                    "surface_area": surface_area,
                    "density": density,
                    "curvature": low_curvature_ratio,
                    "silhouette_score": 0.0,
                    "confidence": _candidate_confidence(0.45 + min(low_curvature_ratio, 0.35)),
                    "rationale": "Dense region in a model with meaningful low-curvature surface area.",
                }
            )
        else:
            candidates.append(
                {
                    "region_id": region_id,
                    "region_type": "dense_high_curvature_region",
                    "recommended_action": "inspect",
                    "triangle_count": triangle_count,
                    "surface_area": surface_area,
                    "density": density,
                    "curvature": high_curvature_ratio,
                    "silhouette_score": 0.0,
                    "confidence": 0.4,
                    "rationale": "Dense but model curvature is high; inspect before decimating.",
                }
            )

    candidates.sort(
        key=lambda item: (
            0 if item["recommended_action"] == "protect_candidate" else 1,
            -int(item["triangle_count"]),
            -float(item["confidence"]),
        )
    )
    return candidates[:40]


def _grid_key(point: Vector, bounds_min: Vector, bounds_max: Vector) -> tuple[int, int, int]:
    size = bounds_max - bounds_min
    key: list[int] = []
    for axis in range(3):
        extent = max(size[axis], 1e-9)
        value = int(((point[axis] - bounds_min[axis]) / extent) * GRID_DIVISIONS)
        key.append(max(0, min(GRID_DIVISIONS - 1, value)))
    return key[0], key[1], key[2]


def _density_bucket(
    density: float,
    thresholds: tuple[float, float, float],
) -> int:
    low, high, extreme = thresholds
    if density <= low:
        return 0
    if density <= high:
        return 1
    if density <= extreme:
        return 2
    return 3


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def _assign_heatmap_materials(
    mesh_objects: list[bpy.types.Object],
    bounds_min: Vector,
    bounds_max: Vector,
    densities: dict[tuple[int, int, int], float],
    thresholds: tuple[float, float, float],
) -> None:
    palette = [
        ("AF_Density_Low_Blue", (0.05, 0.25, 0.95, 1.0)),
        ("AF_Density_Medium_Green", (0.1, 0.75, 0.25, 1.0)),
        ("AF_Density_High_Yellow", (1.0, 0.82, 0.05, 1.0)),
        ("AF_Density_Extreme_Red", (0.95, 0.08, 0.05, 1.0)),
    ]
    materials: list[bpy.types.Material] = []
    for name, color in palette:
        material = bpy.data.materials.new(name)
        material.diffuse_color = color
        materials.append(material)

    for obj in mesh_objects:
        obj.data.materials.clear()
        for material in materials:
            obj.data.materials.append(material)
        for polygon in obj.data.polygons:
            center = obj.matrix_world @ polygon.center
            key = _grid_key(center, bounds_min, bounds_max)
            polygon.material_index = _density_bucket(densities.get(key, 0.0), thresholds)


def _setup_camera_and_light(mesh_objects: list[bpy.types.Object]) -> None:
    bounds_min, bounds_max = _collect_bounds(mesh_objects)
    center = (bounds_min + bounds_max) * 0.5
    size = bounds_max - bounds_min
    radius = max(size.x, size.y, size.z, 1.0)

    bpy.ops.object.light_add(type="AREA", location=(center.x - radius, center.y - radius, center.z + radius))
    light = bpy.context.object
    light.name = "AssetForge Geometry Report Light"
    light.data.energy = 450
    light.data.size = radius * 2.0

    bpy.ops.object.camera_add(
        location=(center.x + radius * 1.8, center.y - radius * 2.2, center.z + radius * 1.4),
        rotation=(math.radians(62), 0, math.radians(40)),
    )
    camera = bpy.context.object
    direction = center - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(radius * 1.35, 1.0)
    bpy.context.scene.camera = camera


def _configure_render(output_path: Path) -> None:
    scene = bpy.context.scene
    scene.render.filepath = str(output_path)
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.film_transparent = False
    scene.world.color = (0.78, 0.80, 0.83)
    try:
        scene.render.engine = "BLENDER_WORKBENCH"
        scene.display.shading.light = "STUDIO"
        scene.display.shading.color_type = "MATERIAL"
    except TypeError:
        if "BLENDER_EEVEE_NEXT" in {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}:
            scene.render.engine = "BLENDER_EEVEE_NEXT"
        else:
            scene.render.engine = "BLENDER_EEVEE"


def _empty_report(source_file: Path, output_directory: Path, message: str) -> dict[str, Any]:
    report_path = output_directory / "geometry_report.json"
    image_path = output_directory / "geometry_report.png"
    return {
        "source_file": str(source_file),
        "report_json_path": str(report_path),
        "heatmap_image_path": str(image_path),
        "overall": {
            "vertices": 0,
            "edges": 0,
            "faces": 0,
            "triangles": 0,
            "bounding_box": {
                "min_x": 0.0,
                "min_y": 0.0,
                "min_z": 0.0,
                "max_x": 0.0,
                "max_y": 0.0,
                "max_z": 0.0,
            },
        },
        "planar_regions": {"region_count": 0, "face_percentage": 0.0, "triangle_percentage": 0.0},
        "curvature": [
            {"name": "Low Curvature", "triangle_count": 0, "percentage": 0.0},
            {"name": "Medium Curvature", "triangle_count": 0, "percentage": 0.0},
            {"name": "High Curvature", "triangle_count": 0, "percentage": 0.0},
        ],
        "boundary": {"count": 0, "length": 0.0},
        "dense_regions": [],
        "silhouette": {
            "view_count": len(SILHOUETTE_VIEWS),
            "total_outline_triangles": 0,
            "protected_triangle_count": 0,
            "protected_triangle_percentage": 0.0,
            "max_hits": 0,
            "views": [
                {"name": name, "outline_triangle_count": 0}
                for name, _direction in SILHOUETTE_VIEWS
            ],
            "top_triangles": [],
            "protected_regions": [],
        },
        "triangle_distribution": {"min_area": 0.0, "max_area": 0.0, "median_area": 0.0},
        "optimization_candidates": [],
        "warnings": [],
        "errors": [message],
    }


def generate(args: argparse.Namespace) -> dict[str, Any]:
    source_file = Path(args.source_file).resolve()
    output_directory = Path(args.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    report_path = output_directory / "geometry_report.json"
    image_path = output_directory / "geometry_report.png"
    warnings: list[str] = []

    if not source_file.exists():
        return _empty_report(source_file, output_directory, f"Model file does not exist: {source_file}")

    _import_source(source_file)
    mesh_objects = _mesh_objects()
    if not mesh_objects:
        return _empty_report(source_file, output_directory, "No mesh objects were found.")

    bounds_min, bounds_max = _collect_bounds(mesh_objects)
    vertex_count = sum(len(obj.data.vertices) for obj in mesh_objects)
    edge_count = sum(len(obj.data.edges) for obj in mesh_objects)
    face_count = sum(len(obj.data.polygons) for obj in mesh_objects)

    triangle_areas: list[float] = []
    total_triangles = 0
    boundary_edges = 0
    boundary_length = 0.0
    total_region_faces = 0
    total_region_triangles = 0
    planar_region_count = 0
    curvature_counts = {"Low Curvature": 0, "Medium Curvature": 0, "High Curvature": 0}
    grid_stats: dict[tuple[int, int, int], dict[str, float]] = defaultdict(
        lambda: {"triangle_count": 0.0, "surface_area": 0.0}
    )
    degenerate_triangle_count = 0

    for obj in mesh_objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        total_triangles += len(mesh.loop_triangles)

        for region in _planar_regions_for_object(obj):
            planar_region_count += 1
            total_region_faces += len(region)
            total_region_triangles += sum(_face_triangle_count(mesh, face_index) for face_index in region)

        object_curvature = _curvature_counts_for_object(obj)
        for key, value in object_curvature.items():
            curvature_counts[key] += value

        edge_to_faces: dict[tuple[int, int], list[int]] = defaultdict(list)
        for polygon in mesh.polygons:
            vertices = list(polygon.vertices)
            for index, first in enumerate(vertices):
                second = vertices[(index + 1) % len(vertices)]
                edge_to_faces[tuple(sorted((first, second)))].append(polygon.index)
        for edge_key, faces in edge_to_faces.items():
            if len(faces) == 1:
                boundary_edges += 1
                a, b = edge_key
                boundary_length += (
                    (obj.matrix_world @ mesh.vertices[a].co)
                    - (obj.matrix_world @ mesh.vertices[b].co)
                ).length

        for triangle in mesh.loop_triangles:
            a, b, c = _world_triangle_vertices(obj, triangle)
            area = _triangle_area(a, b, c)
            triangle_areas.append(area)
            if area <= 1e-12:
                degenerate_triangle_count += 1
            centroid = (a + b + c) / 3.0
            key = _grid_key(centroid, bounds_min, bounds_max)
            grid_stats[key]["triangle_count"] += 1.0
            grid_stats[key]["surface_area"] += area

    if degenerate_triangle_count:
        warnings.append(
            f"{degenerate_triangle_count} zero-area or near-zero-area triangles were excluded "
            "from density ranking."
        )

    densities = {
        key: values["triangle_count"] / values["surface_area"]
        for key, values in grid_stats.items()
        if values["surface_area"] > 1e-9
    }
    density_values = list(densities.values())
    thresholds = (
        _percentile(density_values, 0.50),
        _percentile(density_values, 0.75),
        _percentile(density_values, 0.90),
    )
    dense_regions = sorted(
        (
            {
                "region_id": f"cell_{key[0]}_{key[1]}_{key[2]}",
                "triangle_count": int(values["triangle_count"]),
                "surface_area": values["surface_area"],
                "density": densities[key],
            }
            for key, values in grid_stats.items()
            if key in densities
        ),
        key=lambda item: item["density"],
        reverse=True,
    )[:20]

    try:
        silhouette = _silhouette_analysis(mesh_objects, bounds_min, bounds_max)
    except Exception as exc:  # noqa: BLE001 - keep the rest of the report usable.
        warnings.append(f"Silhouette analysis failed: {exc}")
        silhouette = {
            "view_count": len(SILHOUETTE_VIEWS),
            "total_outline_triangles": 0,
            "protected_triangle_count": 0,
            "protected_triangle_percentage": 0.0,
            "max_hits": 0,
            "views": [
                {"name": name, "outline_triangle_count": 0}
                for name, _direction in SILHOUETTE_VIEWS
            ],
            "top_triangles": [],
            "protected_regions": [],
        }
    optimization_candidates = _optimization_candidates(
        dense_regions,
        silhouette,
        curvature_counts,
        total_triangles,
    )

    _assign_heatmap_materials(mesh_objects, bounds_min, bounds_max, densities, thresholds)
    _setup_camera_and_light(mesh_objects)
    _configure_render(image_path)
    bpy.ops.render.render(write_still=False)
    bpy.data.images["Render Result"].save_render(filepath=str(image_path))

    report = {
        "source_file": str(source_file),
        "report_json_path": str(report_path),
        "heatmap_image_path": str(image_path),
        "overall": {
            "vertices": vertex_count,
            "edges": edge_count,
            "faces": face_count,
            "triangles": total_triangles,
            "bounding_box": {
                "min_x": bounds_min.x,
                "min_y": bounds_min.y,
                "min_z": bounds_min.z,
                "max_x": bounds_max.x,
                "max_y": bounds_max.y,
                "max_z": bounds_max.z,
            },
        },
        "planar_regions": {
            "region_count": planar_region_count,
            "face_percentage": (total_region_faces / face_count * 100.0) if face_count else 0.0,
            "triangle_percentage": (
                total_region_triangles / total_triangles * 100.0
            ) if total_triangles else 0.0,
        },
        "curvature": [
            {
                "name": name,
                "triangle_count": count,
                "percentage": (count / total_triangles * 100.0) if total_triangles else 0.0,
            }
            for name, count in curvature_counts.items()
        ],
        "boundary": {"count": boundary_edges, "length": boundary_length},
        "dense_regions": dense_regions,
        "silhouette": silhouette,
        "triangle_distribution": {
            "min_area": min(triangle_areas) if triangle_areas else 0.0,
            "max_area": max(triangle_areas) if triangle_areas else 0.0,
            "median_area": statistics.median(triangle_areas) if triangle_areas else 0.0,
        },
        "optimization_candidates": optimization_candidates,
        "warnings": warnings,
        "errors": [],
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an AssetForge geometry report.")
    parser.add_argument("--source-file", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--output-json", required=True)
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
