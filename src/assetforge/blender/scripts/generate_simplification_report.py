from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector


GRID_DIVISIONS = 12


def _mesh_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


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


def _grid_key(point: Vector, bounds_min: Vector, bounds_max: Vector) -> tuple[int, int, int]:
    size = bounds_max - bounds_min
    key: list[int] = []
    for axis in range(3):
        extent = max(size[axis], 1e-9)
        value = int(((point[axis] - bounds_min[axis]) / extent) * GRID_DIVISIONS)
        key.append(max(0, min(GRID_DIVISIONS - 1, value)))
    return key[0], key[1], key[2]


def _world_triangle_centroid(
    obj: bpy.types.Object,
    triangle: bpy.types.MeshLoopTriangle,
) -> Vector:
    vertices = obj.data.vertices
    a, b, c = triangle.vertices
    return (
        (obj.matrix_world @ vertices[a].co)
        + (obj.matrix_world @ vertices[b].co)
        + (obj.matrix_world @ vertices[c].co)
    ) / 3.0


def _triangle_grid_counts(
    blend_file: Path,
    bounds_min: Vector | None = None,
    bounds_max: Vector | None = None,
) -> tuple[dict[tuple[str, tuple[int, int, int]], int], int, Vector, Vector]:
    bpy.ops.wm.open_mainfile(filepath=str(blend_file))
    mesh_objects = _mesh_objects()
    if bounds_min is None or bounds_max is None:
        bounds_min, bounds_max = _collect_bounds(mesh_objects)

    counts: dict[tuple[str, tuple[int, int, int]], int] = defaultdict(int)
    total = 0
    for obj in mesh_objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        for triangle in mesh.loop_triangles:
            centroid = _world_triangle_centroid(obj, triangle)
            counts[(obj.name, _grid_key(centroid, bounds_min, bounds_max))] += 1
            total += 1
    return counts, total, bounds_min, bounds_max


def _reduction_ratio(
    key: tuple[str, tuple[int, int, int]],
    original_counts: dict[tuple[str, tuple[int, int, int]], int],
    optimized_counts: dict[tuple[str, tuple[int, int, int]], int],
) -> float:
    original = original_counts.get(key, 0)
    if original <= 0:
        return 0.0
    removed = max(0, original - optimized_counts.get(key, 0))
    return min(1.0, removed / original)


def _bucket_for_ratio(ratio: float) -> int:
    if ratio < 0.15:
        return 0
    if ratio < 0.45:
        return 1
    return 2


def _assign_materials(
    mesh_objects: list[bpy.types.Object],
    bounds_min: Vector,
    bounds_max: Vector,
    original_counts: dict[tuple[str, tuple[int, int, int]], int],
    optimized_counts: dict[tuple[str, tuple[int, int, int]], int],
) -> None:
    palette = [
        ("AF_Simplification_Little_Green", (0.1, 0.75, 0.25, 1.0)),
        ("AF_Simplification_Medium_Yellow", (1.0, 0.82, 0.05, 1.0)),
        ("AF_Simplification_Heavy_Red", (0.95, 0.08, 0.05, 1.0)),
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
            key = (obj.name, _grid_key(center, bounds_min, bounds_max))
            ratio = _reduction_ratio(key, original_counts, optimized_counts)
            polygon.material_index = _bucket_for_ratio(ratio)


def _setup_camera_and_light(mesh_objects: list[bpy.types.Object]) -> None:
    bounds_min, bounds_max = _collect_bounds(mesh_objects)
    center = (bounds_min + bounds_max) * 0.5
    size = bounds_max - bounds_min
    radius = max(size.x, size.y, size.z, 1.0)

    bpy.ops.object.light_add(type="AREA", location=(center.x - radius, center.y - radius, center.z + radius))
    light = bpy.context.object
    light.name = "AssetForge Simplification Light"
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


def _empty_report(
    source_blend_file: Path,
    optimized_blend_file: Path,
    output_directory: Path,
    message: str,
) -> dict[str, Any]:
    return {
        "source_blend_file": str(source_blend_file),
        "optimized_blend_file": str(optimized_blend_file),
        "report_json_path": str(output_directory / "simplification_report.json"),
        "heatmap_image_path": str(output_directory / "simplification_heatmap.png"),
        "original_triangle_count": 0,
        "optimized_triangle_count": 0,
        "removed_triangle_count": 0,
        "reduction_percentage": 0.0,
        "regions": [],
        "warnings": [],
        "errors": [message],
    }


def generate(args: argparse.Namespace) -> dict[str, Any]:
    source_blend_file = Path(args.source_blend_file).resolve()
    optimized_blend_file = Path(args.optimized_blend_file).resolve()
    output_directory = Path(args.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    report_path = output_directory / "simplification_report.json"
    heatmap_path = output_directory / "simplification_heatmap.png"

    if not source_blend_file.exists():
        return _empty_report(
            source_blend_file,
            optimized_blend_file,
            output_directory,
            f"Source blend file does not exist: {source_blend_file}",
        )
    if not optimized_blend_file.exists():
        return _empty_report(
            source_blend_file,
            optimized_blend_file,
            output_directory,
            f"Optimized blend file does not exist: {optimized_blend_file}",
        )

    original_counts, original_total, bounds_min, bounds_max = _triangle_grid_counts(source_blend_file)
    optimized_counts, optimized_total, _, _ = _triangle_grid_counts(
        optimized_blend_file,
        bounds_min,
        bounds_max,
    )
    removed_total = max(0, original_total - optimized_total)
    reduction_percentage = (
        round((removed_total / original_total) * 100.0, 2)
        if original_total
        else 0.0
    )

    regions = []
    for (object_name, key), original in original_counts.items():
        optimized = optimized_counts.get((object_name, key), 0)
        removed = max(0, original - optimized)
        if removed <= 0:
            continue
        regions.append(
            {
                "region_id": f"cell_{key[0]}_{key[1]}_{key[2]}",
                "object_name": object_name,
                "original_triangles": original,
                "optimized_triangles": optimized,
                "removed_triangles": removed,
                "reduction_percentage": round((removed / original) * 100.0, 2),
            }
        )
    regions.sort(
        key=lambda item: (item["removed_triangles"], item["reduction_percentage"]),
        reverse=True,
    )

    bpy.ops.wm.open_mainfile(filepath=str(source_blend_file))
    mesh_objects = _mesh_objects()
    if mesh_objects:
        _assign_materials(mesh_objects, bounds_min, bounds_max, original_counts, optimized_counts)
        _setup_camera_and_light(mesh_objects)
        _configure_render(heatmap_path)
        bpy.ops.render.render(write_still=False)
        bpy.data.images["Render Result"].save_render(filepath=str(heatmap_path))

    report = {
        "source_blend_file": str(source_blend_file),
        "optimized_blend_file": str(optimized_blend_file),
        "report_json_path": str(report_path),
        "heatmap_image_path": str(heatmap_path),
        "original_triangle_count": original_total,
        "optimized_triangle_count": optimized_total,
        "removed_triangle_count": removed_total,
        "reduction_percentage": reduction_percentage,
        "regions": regions[:20],
        "warnings": [],
        "errors": [] if mesh_objects else ["No mesh objects were found in the source blend file."],
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an AssetForge simplification diff report.")
    parser.add_argument("--source-blend-file", required=True)
    parser.add_argument("--optimized-blend-file", required=True)
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
