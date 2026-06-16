from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy


def _mesh_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def _count_object_triangles(obj: bpy.types.Object) -> int:
    obj.data.calc_loop_triangles()
    return len(obj.data.loop_triangles)


def _count_scene_triangles() -> int:
    return sum(_count_object_triangles(obj) for obj in _mesh_objects())


def _preprocessed_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}_preprocessed{source.suffix}")


def _safe_limited_dissolve(mesh_objects: list[bpy.types.Object], angle_degrees: float) -> None:
    angle_limit = math.radians(angle_degrees)
    for obj in mesh_objects:
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.dissolve_limited(angle_limit=angle_limit, use_dissolve_boundaries=False)
        bpy.ops.object.mode_set(mode="OBJECT")
        obj.select_set(False)


def _report(
    source: Path,
    preprocessed: Path,
    report_file: Path,
    original_triangles: int,
    preprocessed_triangles: int,
    angle_degrees: float,
    warnings: list[str],
    errors: list[str],
) -> dict[str, Any]:
    removed = max(0, original_triangles - preprocessed_triangles)
    reduction = round((removed / original_triangles) * 100.0, 2) if original_triangles else 0.0
    return {
        "source_blend_file": str(source),
        "preprocessed_blend_file": str(preprocessed),
        "report_file": str(report_file),
        "original_triangle_count": original_triangles,
        "preprocessed_triangle_count": preprocessed_triangles,
        "removed_triangle_count": removed,
        "reduction_percentage": reduction,
        "limited_dissolve_angle_degrees": angle_degrees,
        "warnings": warnings,
        "errors": errors,
    }


def preprocess(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.blend_file).resolve()
    output_blend = _preprocessed_path(source)
    report_file = output_blend.with_name(f"{output_blend.stem}_report.json")
    warnings: list[str] = []
    errors: list[str] = []

    if not source.exists():
        report = _report(source, output_blend, report_file, 0, 0, args.angle_degrees, [], [
            f"Blend file does not exist: {source}"
        ])
        report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return report

    shutil.copy2(source, output_blend)
    bpy.ops.wm.open_mainfile(filepath=str(output_blend))
    mesh_objects = _mesh_objects()
    original_triangles = _count_scene_triangles()

    if not mesh_objects:
        errors.append("No mesh objects were found.")
    else:
        _safe_limited_dissolve(mesh_objects, args.angle_degrees)

    preprocessed_triangles = _count_scene_triangles()
    if preprocessed_triangles >= original_triangles:
        warnings.append("Safe preprocess did not remove any triangles.")

    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))

    report = _report(
        source,
        output_blend,
        report_file,
        original_triangles,
        preprocessed_triangles,
        args.angle_degrees,
        warnings,
        errors,
    )
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run safe AssetForge mesh preprocess.")
    parser.add_argument("--blend-file", required=True)
    parser.add_argument("--angle-degrees", type=float, default=1.0)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def main() -> int:
    argv = sys.argv
    script_args = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    args = parse_args(script_args)
    report = preprocess(args)
    Path(args.output_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
