from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import bpy

WHEEL_PATTERN = re.compile(r"^Wheel_\d+$")
WHEEL_PREFIXES = ("wheel", "whell")


def _triangles_for_object(obj: bpy.types.Object) -> int:
    mesh = obj.data
    mesh.calc_loop_triangles()
    return len(mesh.loop_triangles)


def _is_strict_wheel_name(name: str) -> bool:
    return WHEEL_PATTERN.match(name) is not None


def _is_wheel_like_name(name: str) -> bool:
    normalized = name.lower()
    return any(normalized.startswith(prefix) for prefix in WHEEL_PREFIXES)


def _largest_mesh_object(mesh_objects: list[bpy.types.Object]) -> bpy.types.Object | None:
    return max(mesh_objects, key=_triangles_for_object, default=None)


def _write_preview_obj(mesh_objects: list[bpy.types.Object], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    vertex_offset = 1
    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("# AssetForge viewport preview mesh\n")
        for obj in mesh_objects:
            mesh = obj.data
            mesh.calc_loop_triangles()
            handle.write(f"o {obj.name}\n")
            for vertex in mesh.vertices:
                world = obj.matrix_world @ vertex.co
                handle.write(f"v {world.x:.6f} {world.y:.6f} {world.z:.6f}\n")
            for triangle in mesh.loop_triangles:
                a, b, c = (index + vertex_offset for index in triangle.vertices)
                handle.write(f"f {a} {b} {c}\n")
            vertex_offset += len(mesh.vertices)


def analyze_blend_file(blend_file: Path, preview_mesh_path: Path | None = None) -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []

    if not blend_file.exists():
        return _error_report(blend_file, f"Blend file does not exist: {blend_file}")

    bpy.ops.wm.open_mainfile(filepath=str(blend_file))

    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    body = next((obj for obj in mesh_objects if obj.name == "VehicleBody"), None)
    strict_wheels = [obj for obj in mesh_objects if _is_strict_wheel_name(obj.name)]
    wheel_like_objects = [obj for obj in mesh_objects if _is_wheel_like_name(obj.name)]
    wheels = strict_wheels or wheel_like_objects

    if body is None:
        non_wheel_objects = [obj for obj in mesh_objects if obj not in wheels]
        if len(non_wheel_objects) == 1 and wheels:
            body = non_wheel_objects[0]
            warnings.append(
                f"VehicleBody was inferred from the only non-wheel mesh object: {body.name}"
            )
        elif mesh_objects:
            body = _largest_mesh_object(mesh_objects)
            warnings.append(
                f"VehicleBody was inferred from the largest mesh object: {body.name}"
            )
        else:
            errors.append(
                "VehicleBody object was not found and no mesh objects were available for body inference."
            )
    if not strict_wheels and wheel_like_objects:
        prefixes = sorted({obj.name.lower().split(".", 1)[0] for obj in wheel_like_objects})
        warnings.append(
            "Wheel objects were inferred from mesh name prefixes: " + ", ".join(prefixes)
        )
    elif not wheels:
        warnings.append("No Wheel_* mesh objects were found.")

    object_summaries: list[dict[str, Any]] = []
    vertex_count = 0
    triangle_count = 0
    for obj in mesh_objects:
        vertices = len(obj.data.vertices)
        triangles = _triangles_for_object(obj)
        vertex_count += vertices
        triangle_count += triangles
        object_summaries.append(
            {
                "name": obj.name,
                "vertex_count": vertices,
                "triangle_count": triangles,
                "is_body": body is not None and obj.name == body.name,
                "is_wheel": any(obj.name == wheel.name for wheel in wheels),
            }
        )

    if preview_mesh_path is not None and mesh_objects:
        _write_preview_obj(mesh_objects, preview_mesh_path)

    return {
        "blend_file": str(blend_file),
        "has_vehicle_body": body is not None,
        "wheel_count": len(wheels),
        "object_count": len(mesh_objects),
        "vertex_count": vertex_count,
        "triangle_count": triangle_count,
        "preview_mesh_path": str(preview_mesh_path) if preview_mesh_path else None,
        "objects": object_summaries,
        "warnings": warnings,
        "errors": errors,
    }


def _error_report(blend_file: Path, message: str) -> dict[str, Any]:
    return {
        "blend_file": str(blend_file),
        "has_vehicle_body": False,
        "wheel_count": 0,
        "object_count": 0,
        "vertex_count": 0,
        "triangle_count": 0,
        "preview_mesh_path": None,
        "objects": [],
        "warnings": [],
        "errors": [message],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze an AssetForge vehicle blend file.")
    parser.add_argument("--blend-file", required=True)
    parser.add_argument("--preview-mesh", default=None)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def main() -> int:
    argv = sys.argv
    script_args = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    args = parse_args(script_args)
    report = analyze_blend_file(
        Path(args.blend_file),
        Path(args.preview_mesh) if args.preview_mesh else None,
    )
    Path(args.output_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
