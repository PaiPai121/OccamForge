from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import bpy

WHEEL_PATTERN = re.compile(r"^Wheel_\d+$")
WHEEL_PREFIXES = ("wheel", "whell")
TEXTURE_SIZE = 1024


def _is_strict_wheel_name(name: str) -> bool:
    return WHEEL_PATTERN.match(name) is not None


def _is_wheel_like_name(name: str) -> bool:
    normalized = name.lower()
    return any(normalized.startswith(prefix) for prefix in WHEEL_PREFIXES)


def _mesh_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def _object_triangle_count(obj: bpy.types.Object) -> int:
    obj.data.calc_loop_triangles()
    return len(obj.data.loop_triangles)


def _largest_mesh_object(mesh_objects: list[bpy.types.Object]) -> bpy.types.Object | None:
    return max(mesh_objects, key=_object_triangle_count, default=None)


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
        elif mesh_objects:
            body = _largest_mesh_object(mesh_objects)
            warnings.append(f"VehicleBody was inferred from the largest mesh object: {body.name}")
        else:
            errors.append("VehicleBody object was not found and no mesh objects were available for body inference.")

    if not strict_wheels and wheel_like:
        prefixes = sorted({obj.name.lower().split(".", 1)[0] for obj in wheel_like})
        warnings.append("Wheel objects were inferred from mesh name prefixes: " + ", ".join(prefixes))
    elif not wheels:
        warnings.append("No wheel objects were detected.")

    return body, wheels, warnings, errors


def _triangle_count(objects: list[bpy.types.Object]) -> int:
    total = 0
    for obj in objects:
        obj.data.calc_loop_triangles()
        total += len(obj.data.loop_triangles)
    return total


def _triangle_count_evaluated(objects: list[bpy.types.Object]) -> int:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    total = 0
    for obj in objects:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        try:
            mesh.calc_loop_triangles()
            total += len(mesh.loop_triangles)
        finally:
            evaluated.to_mesh_clear()
    return total


def _apply_transforms(objects: list[bpy.types.Object]) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        obj.select_set(False)


def _optimize_if_needed(
    objects: list[bpy.types.Object],
    target_triangles: int,
    minimum_ratio: float,
    max_iterations: int,
) -> tuple[bool, int, float]:
    original = _triangle_count(objects)
    if original <= target_triangles:
        return False, original, 1.0

    modifiers: list[tuple[bpy.types.Object, bpy.types.Modifier]] = []
    for obj in objects:
        if len(obj.data.vertices) == 0:
            continue
        modifier = obj.modifiers.new(name="AssetForge_Build_Decimate", type="DECIMATE")
        modifier.decimate_type = "COLLAPSE"
        modifiers.append((obj, modifier))

    low = minimum_ratio
    high = 1.0
    best_ratio = minimum_ratio
    for _ in range(max_iterations):
        ratio = (low + high) / 2.0
        for _, modifier in modifiers:
            modifier.ratio = ratio
        bpy.context.view_layer.update()
        total = _triangle_count_evaluated(objects)
        if total <= target_triangles:
            best_ratio = ratio
            low = ratio
        else:
            high = ratio

    for obj, modifier in modifiers:
        modifier.ratio = best_ratio
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.modifier_apply(modifier=modifier.name)
        obj.select_set(False)

    return True, _triangle_count(objects), best_ratio


def _prepare_materials_for_bake(objects: list[bpy.types.Object], image: bpy.types.Image) -> None:
    for obj in objects:
        if not obj.data.materials:
            mat = bpy.data.materials.new(f"{obj.name}_Material")
            mat.diffuse_color = (0.8, 0.8, 0.8, 1.0)
            obj.data.materials.append(mat)
        for index, material in enumerate(obj.data.materials):
            if material is None:
                material = bpy.data.materials.new(f"{obj.name}_Material_{index}")
                material.diffuse_color = (0.8, 0.8, 0.8, 1.0)
                obj.data.materials[index] = material
            material.use_nodes = True
            nodes = material.node_tree.nodes
            tex_node = nodes.new(type="ShaderNodeTexImage")
            tex_node.image = image
            tex_node.select = True
            nodes.active = tex_node


def _smart_uv_project(objects: list[bpy.types.Object]) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15192, island_margin=0.03, area_weight=0.0)
    bpy.ops.object.mode_set(mode="OBJECT")


def _bake_diffuse_texture(objects: list[bpy.types.Object], texture_file: Path) -> None:
    texture_file = texture_file.resolve()
    bake_objects = [obj for obj in objects if len(obj.data.polygons) > 0]
    if not bake_objects:
        image = bpy.data.images.new("AssetForge_CS_Diffuse", width=TEXTURE_SIZE, height=TEXTURE_SIZE)
        image.filepath_raw = str(texture_file)
        image.file_format = "PNG"
        image.save_render(filepath=str(texture_file))
        return

    image = bpy.data.images.new("AssetForge_CS_Diffuse", width=TEXTURE_SIZE, height=TEXTURE_SIZE)
    _prepare_materials_for_bake(bake_objects, image)
    _smart_uv_project(bake_objects)

    bpy.context.scene.render.engine = "CYCLES"
    bpy.context.scene.cycles.samples = 32
    bpy.context.scene.view_settings.view_transform = "Standard"
    bpy.context.scene.view_settings.look = "Medium High Contrast"
    bpy.context.scene.view_settings.exposure = 0
    bpy.context.scene.view_settings.gamma = 1

    bpy.ops.object.select_all(action="DESELECT")
    for obj in bake_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = bake_objects[0]
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=8)
    image.filepath_raw = str(texture_file)
    image.file_format = "PNG"
    image.save_render(filepath=str(texture_file))


def _apply_cities_skylines_orientation(joined: bpy.types.Object) -> None:
    joined.rotation_euler.rotate_axis("X", math.radians(-90.0))
    bpy.ops.object.select_all(action="DESELECT")
    joined.select_set(True)
    bpy.context.view_layer.objects.active = joined
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def _write_orientation_fix_report(
    report_file: Path,
    output_fbx: Path,
    object_name: str,
) -> None:
    payload = {
        "fbx_file": str(output_fbx),
        "object_name": object_name,
        "rotation_degrees": {"x": -90.0, "y": 0.0, "z": 0.0},
        "applied_rotation": True,
        "applied_scale": True,
        "source_blend_modified": False,
        "reason": "Cities Skylines Asset Editor expects the vehicle to stand upright after import.",
    }
    report_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _export_single_mesh_fbx(
    objects: list[bpy.types.Object],
    output_fbx: Path,
    object_name: str,
    orientation_report_file: Path,
) -> None:
    source_scene = bpy.context.scene
    export_scene = bpy.data.scenes.new("AssetForge_CS_Export")
    copied_objects: list[bpy.types.Object] = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        copied_mesh = obj.data.copy()
        copied = bpy.data.objects.new(obj.name, copied_mesh)
        copied.matrix_world = obj.matrix_world.copy()
        export_scene.collection.objects.link(copied)
        copied_objects.append(copied)

    if not copied_objects:
        raise RuntimeError("No mesh objects available for FBX export.")

    bpy.context.window.scene = export_scene
    bpy.ops.object.select_all(action="DESELECT")
    for obj in copied_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = copied_objects[0]
    _apply_transforms(copied_objects)

    bpy.ops.object.select_all(action="DESELECT")
    for obj in copied_objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = copied_objects[0]
    bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined.name = object_name
    joined.data.name = f"{object_name}_Mesh"
    _apply_cities_skylines_orientation(joined)

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
    _write_orientation_fix_report(orientation_report_file, output_fbx, object_name)
    bpy.context.window.scene = source_scene
    bpy.data.scenes.remove(export_scene)


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not create a unique output path for {path}")


def _unique_asset_base(folder: Path, base_name: str) -> str:
    for index in range(0, 1000):
        suffix = "" if index == 0 else f"_{index:03d}"
        candidate = f"{base_name}{suffix}"
        fbx_path = folder / f"{candidate}.fbx"
        diffuse_path = folder / f"{candidate}_d.png"
        if not fbx_path.exists() and not diffuse_path.exists():
            return candidate
    raise RuntimeError(f"Could not create a unique asset base name for {base_name}")


def _copy_deploy_pair(
    fbx_file: Path,
    diffuse_file: Path,
    deploy_folder: Path,
    base_name: str,
) -> tuple[Path, Path]:
    deploy_folder.mkdir(parents=True, exist_ok=True)
    asset_base = _unique_asset_base(deploy_folder, base_name)
    deployed_fbx = deploy_folder / f"{asset_base}.fbx"
    deployed_diffuse = deploy_folder / f"{asset_base}_d.png"
    shutil.copy2(fbx_file, deployed_fbx)
    shutil.copy2(diffuse_file, deployed_diffuse)
    return deployed_fbx, deployed_diffuse


def build(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.blend_file)
    build_folder = Path(args.build_folder) if args.build_folder else source.parent / "build"
    deploy_folder = Path(args.deploy_folder) if args.deploy_folder else build_folder
    build_folder.mkdir(parents=True, exist_ok=True)
    working_blend = _unique_path(build_folder / f"{source.stem}_build.blend")
    fbx_file = _unique_path(build_folder / f"{source.stem}_cs.fbx")
    diffuse_file = _unique_path(build_folder / f"{source.stem}_cs_d.png")
    report_file = _unique_path(build_folder / "build_report.json")
    orientation_report_file = _unique_path(build_folder / "orientation_fix_report.json")
    deployed_fbx_file: Path | None = None
    deployed_diffuse_file: Path | None = None
    warnings: list[str] = []
    errors: list[str] = []

    if not source.exists():
        return _write_and_return(
            _report(source, build_folder, deploy_folder, working_blend, fbx_file, diffuse_file, deployed_fbx_file, deployed_diffuse_file, report_file, args.profile_id, 0, 0, args.target_triangles, False, None, 0, 0, warnings, [f"Blend file does not exist: {source}"]),
            report_file,
        )

    shutil.copy2(source, working_blend)
    bpy.ops.wm.open_mainfile(filepath=str(working_blend))
    objects = _mesh_objects()
    body, wheels, classify_warnings, classify_errors = _classify(objects)
    warnings.extend(classify_warnings)
    errors.extend(classify_errors)
    original_triangles = _triangle_count(objects)

    if errors:
        return _write_and_return(
            _report(source, build_folder, deploy_folder, working_blend, fbx_file, diffuse_file, deployed_fbx_file, deployed_diffuse_file, report_file, args.profile_id, original_triangles, original_triangles, args.target_triangles, False, body.name if body else None, len(wheels), len(objects), warnings, errors),
            report_file,
        )

    _apply_transforms(objects)
    if args.optimize:
        optimized, final_triangles, _ = _optimize_if_needed(
            objects,
            args.target_triangles,
            args.minimum_ratio,
            args.max_iterations,
        )
    else:
        optimized = False
        final_triangles = original_triangles
        warnings.append("Optimization disabled; original mesh triangle count was preserved.")
    if final_triangles > args.warning_triangles:
        warnings.append(
            f"Final triangle count {final_triangles} is above Cities Skylines warning limit {args.warning_triangles}."
        )

    _bake_diffuse_texture(objects, diffuse_file)
    if not diffuse_file.exists():
        errors.append(f"Diffuse texture was not generated: {diffuse_file}")
        return _write_and_return(
            _report(source, build_folder, deploy_folder, working_blend, fbx_file, diffuse_file, deployed_fbx_file, deployed_diffuse_file, report_file, args.profile_id, original_triangles, final_triangles, args.target_triangles, optimized, body.name if body else None, len(wheels), len(objects), warnings, errors),
            report_file,
        )
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(working_blend))
    _export_single_mesh_fbx(objects, fbx_file, f"{source.stem}_cs", orientation_report_file)
    warnings.append("Cities Skylines FBX exported as a single joined mesh for Asset Editor compatibility.")
    warnings.append("Cities Skylines orientation fix applied: export mesh rotated -90 degrees on X axis.")

    if deploy_folder.resolve() == build_folder.resolve():
        deployed_fbx_file = fbx_file
        deployed_diffuse_file = diffuse_file
    else:
        deployed_fbx_file, deployed_diffuse_file = _copy_deploy_pair(
            fbx_file,
            diffuse_file,
            deploy_folder,
            f"{source.stem}_cs",
        )
        warnings.append(f"Deployed Cities Skylines import files to {deploy_folder}.")

    return _write_and_return(
        _report(source, build_folder, deploy_folder, working_blend, fbx_file, diffuse_file, deployed_fbx_file, deployed_diffuse_file, report_file, args.profile_id, original_triangles, final_triangles, args.target_triangles, optimized, body.name if body else None, len(wheels), len(objects), warnings, []),
        report_file,
    )


def _report(
    source: Path,
    build_folder: Path,
    deploy_folder: Path | None,
    working_blend: Path,
    fbx_file: Path,
    diffuse_file: Path,
    deployed_fbx_file: Path | None,
    deployed_diffuse_file: Path | None,
    report_file: Path,
    profile_id: str,
    original_triangles: int,
    final_triangles: int,
    target_triangles: int,
    optimized: bool,
    body_object: str | None,
    wheel_count: int,
    object_count: int,
    warnings: list[str],
    errors: list[str],
) -> dict[str, Any]:
    return {
        "source_blend_file": str(source),
        "build_folder": str(build_folder),
        "deploy_folder": str(deploy_folder) if deploy_folder else None,
        "working_blend_file": str(working_blend),
        "fbx_file": str(fbx_file),
        "diffuse_texture_file": str(diffuse_file),
        "deployed_fbx_file": str(deployed_fbx_file) if deployed_fbx_file else None,
        "deployed_diffuse_texture_file": str(deployed_diffuse_file) if deployed_diffuse_file else None,
        "report_file": str(report_file),
        "profile_id": profile_id,
        "original_triangle_count": original_triangles,
        "final_triangle_count": final_triangles,
        "target_triangle_count": target_triangles,
        "optimized": optimized,
        "body_object": body_object,
        "wheel_count": wheel_count,
        "object_count": object_count,
        "warnings": warnings,
        "errors": errors,
    }


def _write_and_return(report: dict[str, Any], report_file: Path) -> dict[str, Any]:
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Cities Skylines vehicle package.")
    parser.add_argument("--blend-file", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--target-triangles", type=int, required=True)
    parser.add_argument("--warning-triangles", type=int, required=True)
    parser.add_argument("--critical-triangles", type=int, required=True)
    parser.add_argument("--minimum-ratio", type=float, required=True)
    parser.add_argument("--max-iterations", type=int, required=True)
    parser.add_argument("--build-folder", default=None)
    parser.add_argument("--deploy-folder", default=None)
    parser.add_argument("--optimize", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    argv = sys.argv
    script_args = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    args = parse_args(script_args)
    report = build(args)
    Path(args.output_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
