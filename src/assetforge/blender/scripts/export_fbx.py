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


def _is_strict_wheel_name(name: str) -> bool:
    return WHEEL_PATTERN.match(name) is not None


def _is_wheel_like_name(name: str) -> bool:
    normalized = name.lower()
    return any(normalized.startswith(prefix) for prefix in WHEEL_PREFIXES)


def _mesh_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def _classify(mesh_objects: list[bpy.types.Object]) -> tuple[bpy.types.Object | None, list[bpy.types.Object], list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    body = next((obj for obj in mesh_objects if obj.name == "VehicleBody"), None)
    strict_wheels = [obj for obj in mesh_objects if _is_strict_wheel_name(obj.name)]
    wheel_like = [obj for obj in mesh_objects if _is_wheel_like_name(obj.name)]
    wheels = strict_wheels or wheel_like

    if body is None:
        non_wheel = [obj for obj in mesh_objects if obj not in wheels]
        if len(non_wheel) == 1 and wheels:
            body = non_wheel[0]
            warnings.append(f"VehicleBody was inferred from the only non-wheel mesh object: {body.name}")
        else:
            errors.append("VehicleBody object was not found and body could not be inferred from object names.")

    if not strict_wheels and wheel_like:
        prefixes = sorted({obj.name.lower().split(".", 1)[0] for obj in wheel_like})
        warnings.append("Wheel objects were inferred from mesh name prefixes: " + ", ".join(prefixes))
    elif not wheels:
        warnings.append("No Wheel_* mesh objects were found.")

    return body, wheels, warnings, errors


def _triangle_count(objects: list[bpy.types.Object]) -> int:
    total = 0
    for obj in objects:
        obj.data.calc_loop_triangles()
        total += len(obj.data.loop_triangles)
    return total


def _apply_transforms(objects: list[bpy.types.Object]) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        obj.select_set(False)


def export_fbx(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source_blend_file)
    export_blend = Path(args.export_blend_file)
    output_fbx = Path(args.output_fbx)

    if not export_blend.exists():
        return _report(source, export_blend, output_fbx, args.profile_id, 0, 0, 0, [], [f"Export blend file does not exist: {export_blend}"])

    bpy.ops.wm.open_mainfile(filepath=str(export_blend))
    mesh_objects = _mesh_objects()
    _, wheels, warnings, errors = _classify(mesh_objects)
    if errors:
        return _report(source, export_blend, output_fbx, args.profile_id, _triangle_count(mesh_objects), len(wheels), len(mesh_objects), warnings, errors)

    _apply_transforms(mesh_objects)
    triangle_count = _triangle_count(mesh_objects)

    bpy.ops.object.select_all(action="DESELECT")
    for obj in mesh_objects:
        obj.select_set(True)

    output_fbx.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=str(output_fbx),
        use_selection=True,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",
        bake_space_transform=False,
        object_types={"MESH", "EMPTY"},
        use_mesh_modifiers=True,
        mesh_smooth_type="FACE",
        add_leaf_bones=False,
        axis_forward="-Z",
        axis_up="Y",
        global_scale=1.0,
        path_mode="AUTO",
    )

    return _report(
        source,
        export_blend,
        output_fbx,
        args.profile_id,
        triangle_count,
        len(wheels),
        len(mesh_objects),
        warnings,
        [],
    )


def _report(
    source: Path,
    export_blend: Path,
    output_fbx: Path,
    profile_id: str,
    triangle_count: int,
    wheel_count: int,
    object_count: int,
    warnings: list[str],
    errors: list[str],
) -> dict[str, Any]:
    return {
        "source_blend_file": str(source),
        "export_blend_file": str(export_blend),
        "fbx_file": str(output_fbx),
        "profile_id": profile_id,
        "triangle_count": triangle_count,
        "wheel_count": wheel_count,
        "object_count": object_count,
        "warnings": warnings,
        "errors": errors,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export an AssetForge vehicle to FBX.")
    parser.add_argument("--source-blend-file", required=True)
    parser.add_argument("--export-blend-file", required=True)
    parser.add_argument("--output-fbx", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--profile-id", required=True)
    return parser.parse_args(argv)


def main() -> int:
    argv = sys.argv
    script_args = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    args = parse_args(script_args)
    report = export_fbx(args)
    Path(args.output_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

