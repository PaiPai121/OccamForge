from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy

WHEEL_PATTERN = re.compile(r"^Wheel_\d+$")
WHEEL_PREFIXES = ("wheel", "whell")


def _is_strict_wheel_name(name: str) -> bool:
    return WHEEL_PATTERN.match(name) is not None


def _is_wheel_like_name(name: str) -> bool:
    normalized = name.lower()
    return any(normalized.startswith(prefix) for prefix in WHEEL_PREFIXES)


def _mesh_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def _classify_vehicle(mesh_objects: list[bpy.types.Object]) -> tuple[bpy.types.Object | None, list[bpy.types.Object], list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    body = next((obj for obj in mesh_objects if obj.name == "VehicleBody"), None)
    strict_wheels = [obj for obj in mesh_objects if _is_strict_wheel_name(obj.name)]
    wheel_like_objects = [obj for obj in mesh_objects if _is_wheel_like_name(obj.name)]
    wheels = strict_wheels or wheel_like_objects

    if body is None:
        non_wheel_objects = [obj for obj in mesh_objects if obj not in wheels]
        if len(non_wheel_objects) == 1 and wheels:
            body = non_wheel_objects[0]
            warnings.append(f"VehicleBody was inferred from the only non-wheel mesh object: {body.name}")
        else:
            errors.append("VehicleBody object was not found and body could not be inferred from object names.")

    if not strict_wheels and wheel_like_objects:
        prefixes = sorted({obj.name.lower().split(".", 1)[0] for obj in wheel_like_objects})
        warnings.append("Wheel objects were inferred from mesh name prefixes: " + ", ".join(prefixes))
    elif not wheels:
        warnings.append("No Wheel_* mesh objects were found.")

    return body, wheels, warnings, errors


def _count_object_triangles(obj: bpy.types.Object) -> int:
    mesh = obj.data
    mesh.calc_loop_triangles()
    return len(mesh.loop_triangles)


def _count_scene_triangles(mesh_objects: list[bpy.types.Object]) -> int:
    return sum(_count_object_triangles(obj) for obj in mesh_objects)


def _count_scene_triangles_evaluated(mesh_objects: list[bpy.types.Object]) -> int:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    total = 0
    for obj in mesh_objects:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            total += len(mesh.loop_triangles)
        finally:
            evaluated.to_mesh_clear()
    return total


def _apply_transforms(mesh_objects: list[bpy.types.Object]) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in mesh_objects:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        obj.select_set(False)


def _optimize_objects(
    decimate_objects: list[bpy.types.Object],
    mesh_objects: list[bpy.types.Object],
    target_triangles: int,
    minimum_ratio: float,
    max_iterations: int,
) -> tuple[int, float, int, list[str]]:
    warnings: list[str] = []
    original_total = _count_scene_triangles(mesh_objects)
    if original_total <= target_triangles:
        warnings.append("Original triangle count is already at or below the target.")
        return original_total, 1.0, 0, warnings

    modifiers: list[tuple[bpy.types.Object, bpy.types.Modifier]] = []
    for obj in decimate_objects:
        modifier = obj.modifiers.new(name="AssetForge_Decimate", type="DECIMATE")
        modifier.decimate_type = "COLLAPSE"
        modifiers.append((obj, modifier))

    low = minimum_ratio
    high = 1.0
    best_ratio = minimum_ratio
    best_total = original_total
    iterations = 0

    for _ in range(max_iterations):
        iterations += 1
        ratio = (low + high) / 2.0
        for _, modifier in modifiers:
            modifier.ratio = ratio
        bpy.context.view_layer.update()
        total = _count_scene_triangles_evaluated(mesh_objects)

        if total <= target_triangles:
            best_ratio = ratio
            best_total = total
            low = ratio
        else:
            high = ratio

    for obj, modifier in modifiers:
        modifier.ratio = best_ratio
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        obj.select_set(False)
    optimized_total = _count_scene_triangles(mesh_objects)

    if best_total > target_triangles:
        warnings.append(
            "Target triangle count could not be reached with the configured minimum decimate ratio."
        )
    return optimized_total, best_ratio, iterations, warnings


def _optimized_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}_optimized{source.suffix}")


def optimize_blend_file(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.blend_file)
    output_blend = _optimized_path(source)
    report_file = output_blend.with_name(f"{output_blend.stem}_report.json")
    warnings: list[str] = []
    errors: list[str] = []

    if not source.exists():
        return _error_report(source, output_blend, report_file, args.profile_id, args.target_triangles, f"Blend file does not exist: {source}")

    shutil.copy2(source, output_blend)
    bpy.ops.wm.open_mainfile(filepath=str(output_blend))

    mesh_objects = _mesh_objects()
    body, wheels, classify_warnings, classify_errors = _classify_vehicle(mesh_objects)
    warnings.extend(classify_warnings)
    errors.extend(classify_errors)

    if body is None or errors:
        report = _report(
            source=source,
            output_blend=output_blend,
            report_file=report_file,
            profile_id=args.profile_id,
            target_triangles=args.target_triangles,
            original_triangles=_count_scene_triangles(mesh_objects),
            optimized_triangles=_count_scene_triangles(mesh_objects),
            body_object=body.name if body else None,
            wheel_count=len(wheels),
            decimate_ratio=1.0,
            iterations=0,
            warnings=warnings,
            errors=errors,
        )
        _write_report(report, report_file)
        return report

    _apply_transforms(mesh_objects)
    original_triangles = _count_scene_triangles(mesh_objects)
    decimate_objects = [body] if args.decimate_body_only else mesh_objects
    optimized_triangles, ratio, iterations, optimize_warnings = _optimize_objects(
        decimate_objects=decimate_objects,
        mesh_objects=mesh_objects,
        target_triangles=args.target_triangles,
        minimum_ratio=args.minimum_ratio,
        max_iterations=args.max_iterations,
    )
    warnings.extend(optimize_warnings)

    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))

    report = _report(
        source=source,
        output_blend=output_blend,
        report_file=report_file,
        profile_id=args.profile_id,
        target_triangles=args.target_triangles,
        original_triangles=original_triangles,
        optimized_triangles=optimized_triangles,
        body_object=body.name,
        wheel_count=len(wheels),
        decimate_ratio=ratio,
        iterations=iterations,
        warnings=warnings,
        errors=errors,
    )
    _write_report(report, report_file)
    return report


def _report(
    source: Path,
    output_blend: Path,
    report_file: Path,
    profile_id: str,
    target_triangles: int,
    original_triangles: int,
    optimized_triangles: int,
    body_object: str | None,
    wheel_count: int,
    decimate_ratio: float,
    iterations: int,
    warnings: list[str],
    errors: list[str],
) -> dict[str, Any]:
    reduction = 0.0
    if original_triangles > 0:
        reduction = round(((original_triangles - optimized_triangles) / original_triangles) * 100.0, 2)
    return {
        "source_blend_file": str(source),
        "optimized_blend_file": str(output_blend),
        "report_file": str(report_file),
        "profile_id": profile_id,
        "target_triangle_count": target_triangles,
        "original_triangle_count": original_triangles,
        "optimized_triangle_count": optimized_triangles,
        "reduction_percentage": reduction,
        "body_object": body_object,
        "wheel_count": wheel_count,
        "decimate_ratio": round(decimate_ratio, 4),
        "iterations": iterations,
        "warnings": warnings,
        "errors": errors,
    }


def _error_report(source: Path, output_blend: Path, report_file: Path, profile_id: str, target_triangles: int, message: str) -> dict[str, Any]:
    return _report(
        source=source,
        output_blend=output_blend,
        report_file=report_file,
        profile_id=profile_id,
        target_triangles=target_triangles,
        original_triangles=0,
        optimized_triangles=0,
        body_object=None,
        wheel_count=0,
        decimate_ratio=1.0,
        iterations=0,
        warnings=[],
        errors=[message],
    )


def _write_report(report: dict[str, Any], report_file: Path) -> None:
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")


def _parse_bool(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize an AssetForge vehicle blend file.")
    parser.add_argument("--blend-file", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--target-triangles", type=int, required=True)
    parser.add_argument("--minimum-ratio", type=float, required=True)
    parser.add_argument("--max-iterations", type=int, required=True)
    parser.add_argument("--preserve-wheels", type=_parse_bool, required=True)
    parser.add_argument("--decimate-body-only", type=_parse_bool, required=True)
    return parser.parse_args(argv)


def main() -> int:
    argv = sys.argv
    script_args = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    args = parse_args(script_args)
    report = optimize_blend_file(args)
    Path(args.output_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
