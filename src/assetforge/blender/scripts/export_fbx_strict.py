from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bpy


def _mesh_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


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


def _remove_non_mesh_objects() -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in list(bpy.context.scene.objects):
        if obj.type != "MESH":
            obj.select_set(True)
    bpy.ops.object.delete()


def _join_mesh_objects(output_name: str) -> bpy.types.Object | None:
    mesh_objects = _mesh_objects()
    if not mesh_objects:
        return None
    bpy.ops.object.select_all(action="DESELECT")
    for obj in mesh_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_objects[0]
    bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined.name = output_name
    joined.data.name = f"{output_name}_Mesh"
    return joined


def export_strict(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source_blend_file)
    export_blend = Path(args.export_blend_file)
    output_fbx = Path(args.output_fbx)
    warnings: list[str] = [
        "Strict export experiment: all mesh objects are joined into one mesh for import compatibility testing."
    ]
    errors: list[str] = []

    if not export_blend.exists():
        return _report(source, export_blend, output_fbx, args.profile_id, 0, 0, 0, warnings, [f"Export blend file does not exist: {export_blend}"])

    bpy.ops.wm.open_mainfile(filepath=str(export_blend))
    _remove_non_mesh_objects()
    mesh_objects = _mesh_objects()
    original_object_count = len(mesh_objects)
    if not mesh_objects:
        return _report(source, export_blend, output_fbx, args.profile_id, 0, 0, 0, warnings, ["No mesh objects found."])

    _apply_transforms(mesh_objects)
    triangle_count = _triangle_count(mesh_objects)
    joined = _join_mesh_objects(f"{source.stem}_strict")
    if joined is None:
        errors.append("Failed to join mesh objects.")
        return _report(source, export_blend, output_fbx, args.profile_id, triangle_count, 0, 0, warnings, errors)

    bpy.ops.object.select_all(action="DESELECT")
    joined.select_set(True)
    bpy.context.view_layer.objects.active = joined
    output_fbx.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=str(output_fbx),
        use_selection=True,
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",
        bake_space_transform=False,
        object_types={"MESH"},
        use_mesh_modifiers=True,
        mesh_smooth_type="FACE",
        add_leaf_bones=False,
        axis_forward="-Z",
        axis_up="Y",
        global_scale=1.0,
        path_mode="AUTO",
    )

    warnings.append(f"Joined {original_object_count} mesh objects into one exported mesh.")
    return _report(
        source,
        export_blend,
        output_fbx,
        args.profile_id,
        triangle_count,
        0,
        1,
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
    parser = argparse.ArgumentParser(description="Export a strict single-mesh FBX experiment.")
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
    report = export_strict(args)
    Path(args.output_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

