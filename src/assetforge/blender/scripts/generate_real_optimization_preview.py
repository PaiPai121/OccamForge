from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).parent))

from optimize_vehicle import (
    _apply_transforms,
    _classify_vehicle,
    _count_scene_triangles,
    _mesh_objects,
    _optimize_objects,
)


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


def _scene_bounds(mesh_objects: list[bpy.types.Object]) -> tuple[Vector, float]:
    points = [obj.matrix_world @ Vector(corner) for obj in mesh_objects for corner in obj.bound_box]
    if not points:
        return Vector((0.0, 0.0, 0.0)), 1.0
    minimum = Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points)))
    maximum = Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points)))
    center = (minimum + maximum) / 2.0
    diagonal = max((maximum - minimum).length, 1.0)
    return center, diagonal


def _look_at(obj: bpy.types.Object, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _setup_camera_and_light(mesh_objects: list[bpy.types.Object]) -> None:
    for obj in list(bpy.context.scene.objects):
        if obj.type in {"CAMERA", "LIGHT"}:
            bpy.data.objects.remove(obj, do_unlink=True)

    center, diagonal = _scene_bounds(mesh_objects)
    camera_data = bpy.data.cameras.new("AssetForge_Preview_Camera")
    camera = bpy.data.objects.new("AssetForge_Preview_Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = center + Vector((diagonal * 0.9, -diagonal * 1.8, diagonal * 0.8))
    camera_data.lens = 55
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
        actual_triangles, _, _, optimize_warnings = _optimize_objects(
            decimate_objects=decimate_objects,
            mesh_objects=mesh_objects,
            target_triangles=target,
            minimum_ratio=args.minimum_ratio,
            max_iterations=args.max_iterations,
        )
        warnings.extend(optimize_warnings)
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
