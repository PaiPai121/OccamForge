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


def _object_triangle_count(obj: bpy.types.Object) -> int:
    obj.data.calc_loop_triangles()
    return len(obj.data.loop_triangles)


def _largest_mesh_object(mesh_objects: list[bpy.types.Object]) -> bpy.types.Object | None:
    return max(mesh_objects, key=_object_triangle_count, default=None)


def _classify(mesh_objects: list[bpy.types.Object]) -> tuple[bpy.types.Object | None, list[bpy.types.Object], list[bpy.types.Object], list[dict[str, str]]]:
    issues: list[dict[str, str]] = []
    body = next((obj for obj in mesh_objects if obj.name == "VehicleBody"), None)
    strict_wheels = [obj for obj in mesh_objects if _is_strict_wheel_name(obj.name)]
    wheel_like = [obj for obj in mesh_objects if _is_wheel_like_name(obj.name)]
    wheels = strict_wheels or wheel_like

    if body is None:
        non_wheel = [obj for obj in mesh_objects if obj not in wheels]
        if len(non_wheel) == 1 and wheels:
            body = non_wheel[0]
            issues.append(
                _issue("body_detection", "warning", f"Body inferred from only non-wheel mesh: {body.name}")
            )
        elif mesh_objects:
            body = _largest_mesh_object(mesh_objects)
            issues.append(
                _issue("body_detection", "warning", f"Body inferred from largest mesh object: {body.name}")
            )
        else:
            issues.append(_issue("body_detection", "critical", "Vehicle body could not be detected."))

    if not strict_wheels and wheel_like:
        prefixes = sorted({obj.name.lower().split(".", 1)[0] for obj in wheel_like})
        issues.append(
            _issue("wheel_detection", "warning", "Wheels inferred from prefixes: " + ", ".join(prefixes))
        )
    elif not wheels:
        issues.append(_issue("wheel_detection", "warning", "No wheel objects were detected."))

    known = set(wheels)
    if body is not None:
        known.add(body)
    unknown = [obj for obj in mesh_objects if obj not in known]
    return body, wheels, unknown, issues


def _triangle_count(objects: list[bpy.types.Object]) -> int:
    total = 0
    for obj in objects:
        obj.data.calc_loop_triangles()
        total += len(obj.data.loop_triangles)
    return total


def _has_unapplied_transform(obj: bpy.types.Object) -> bool:
    rot_bad = any(abs(value) > 0.0001 for value in obj.rotation_euler)
    scale_bad = any(abs(value - 1.0) > 0.0001 for value in obj.scale)
    return rot_bad or scale_bad


def _has_image_texture(obj: bpy.types.Object) -> bool:
    if not obj.data.materials:
        return False
    for material in obj.data.materials:
        if material is None:
            continue
        if material.use_nodes:
            for node in material.node_tree.nodes:
                if node.type == "TEX_IMAGE" and getattr(node, "image", None) is not None:
                    return True
        elif material.diffuse_color is not None:
            return True
    return False


def _lod_names(objects: list[bpy.types.Object]) -> set[str]:
    lods: set[str] = set()
    for obj in objects:
        lowered = obj.name.lower()
        match = re.search(r"lod[_\s-]?(\d+)", lowered)
        if match:
            lods.add(f"lod{match.group(1)}")
    return lods


def _triangle_issue(triangle_count: int, preferred: int, warning: int, critical: int) -> dict[str, str] | None:
    if triangle_count > critical:
        return _issue("triangle_count", "critical", f"Triangle count {triangle_count} exceeds critical limit {critical}.")
    if triangle_count > warning:
        return _issue("triangle_count", "warning", f"Triangle count {triangle_count} exceeds warning limit {warning}.")
    if triangle_count >= preferred:
        return _issue("triangle_count", "info", f"Triangle count {triangle_count} is above preferred target {preferred}.")
    return None


def _score(issues: list[dict[str, str]]) -> int:
    score = 100
    for issue in issues:
        severity = issue["severity"]
        if severity == "critical":
            score -= 35
        elif severity == "warning":
            score -= 15
        elif severity == "info":
            score -= 5
    return max(0, min(100, score))


def _rating(score: int, issues: list[dict[str, str]]) -> str:
    if any(issue["severity"] == "critical" for issue in issues):
        return "Critical"
    if score < 75:
        return "Warning"
    if score < 90:
        return "Good"
    return "Excellent"


def _issue(check: str, severity: str, message: str) -> dict[str, str]:
    return {"check": check, "severity": severity, "message": message}


def validate(args: argparse.Namespace) -> dict[str, Any]:
    blend_file = Path(args.blend_file)
    report_file = blend_file.with_name("validation_report.json")
    if not blend_file.exists():
        report = _empty_report(blend_file, report_file, args.profile_id, "Blend file does not exist.")
        _write_report(report, report_file)
        return report

    bpy.ops.wm.open_mainfile(filepath=str(blend_file))
    mesh_objects = _mesh_objects()
    body, wheels, unknown, issues = _classify(mesh_objects)
    triangle_count = _triangle_count(mesh_objects)

    triangle_issue = _triangle_issue(
        triangle_count,
        args.preferred_triangles,
        args.warning_triangles,
        args.critical_triangles,
    )
    if triangle_issue is not None:
        issues.append(triangle_issue)

    unapplied = [obj.name for obj in mesh_objects if _has_unapplied_transform(obj)]
    if unapplied:
        issues.append(_issue("unapplied_transforms", "warning", f"{len(unapplied)} objects have unapplied transforms."))

    auto_texture_candidates = [obj.name for obj in mesh_objects if not _has_image_texture(obj)]
    if auto_texture_candidates:
        issues.append(
            _issue(
                "auto_texture_generation",
                "info",
                f"Can auto-generate diffuse texture for {len(auto_texture_candidates)} mesh objects.",
            )
        )

    lods = _lod_names(mesh_objects)
    missing_lods = tuple(lod for lod in ("lod0", "lod1", "lod2") if lod not in lods)
    if missing_lods:
        issues.append(_issue("missing_lods", "warning", "Missing LOD markers: " + ", ".join(missing_lods)))

    if len(mesh_objects) == 0:
        issues.append(_issue("object_count", "critical", "No mesh objects found."))
    elif len(mesh_objects) > 200:
        issues.append(_issue("object_count", "warning", f"High object count: {len(mesh_objects)}."))

    score = _score(issues)
    rating = _rating(score, issues)
    export_ready = not any(issue["severity"] == "critical" for issue in issues)
    import_readiness = _import_readiness(blend_file)

    report = {
        "blend_file": str(blend_file),
        "report_file": str(report_file),
        "profile_id": args.profile_id,
        "triangle_count": triangle_count,
        "wheel_count": len(wheels),
        "object_count": len(mesh_objects),
        "blender_path": bpy.app.binary_path,
        "body_object": body.name if body is not None else None,
        "wheel_objects": [obj.name for obj in wheels],
        "unknown_objects": [obj.name for obj in unknown],
        "unapplied_transform_objects": unapplied,
        "auto_texture_candidate_objects": auto_texture_candidates,
        "missing_lods": list(missing_lods),
        "score": score,
        "rating": rating,
        "export_ready": export_ready,
        "import_readiness": import_readiness,
        "issues": issues,
        "messages": [issue["message"] for issue in issues],
    }
    _write_report(report, report_file)
    return report


def _empty_report(blend_file: Path, report_file: Path, profile_id: str, message: str) -> dict[str, Any]:
    issue = _issue("file", "critical", message)
    return {
        "blend_file": str(blend_file),
        "report_file": str(report_file),
        "profile_id": profile_id,
        "triangle_count": 0,
        "wheel_count": 0,
        "object_count": 0,
        "blender_path": bpy.app.binary_path,
        "body_object": None,
        "wheel_objects": [],
        "unknown_objects": [],
        "unapplied_transform_objects": [],
        "auto_texture_candidate_objects": [],
        "missing_lods": ["lod0", "lod1", "lod2"],
        "score": 0,
        "rating": "Critical",
        "export_ready": False,
        "import_readiness": _import_readiness(blend_file),
        "issues": [issue],
        "messages": [message],
    }


def _write_report(report: dict[str, Any], report_file: Path) -> None:
    report_file.write_text(json.dumps(report, indent=2), encoding="utf-8")


def _import_readiness(blend_file: Path) -> dict[str, Any]:
    source_stem = blend_file.stem.removesuffix("_optimized").removesuffix("_build")
    package_folder = blend_file.parent / "build"
    fbx_file = package_folder / f"{source_stem}_cs.fbx"
    diffuse_texture_file = package_folder / f"{source_stem}_cs_d.png"
    build_report_file = package_folder / "build_report.json"
    files_ready = fbx_file.exists() and diffuse_texture_file.exists() and build_report_file.exists()
    return {
        "package_folder": str(package_folder),
        "fbx_file": str(fbx_file),
        "diffuse_texture_file": str(diffuse_texture_file),
        "build_report_file": str(build_report_file),
        "files_ready": files_ready,
        "blender_fbx_import_ready": False,
        "import_ready": files_ready,
        "cities_skylines_editor_status": "manual_required",
        "manual_steps": [
            "Open Cities Skylines.",
            "Open Tools > Asset Editor.",
            "Choose Vehicle asset type/template.",
            "Import the generated _cs.fbx from the build folder.",
            "Confirm model orientation, scale, wheel placement, and texture assignment.",
            "Save the asset in Asset Editor.",
        ],
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an AssetForge vehicle blend file.")
    parser.add_argument("--blend-file", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--profile-id", required=True)
    parser.add_argument("--preferred-triangles", type=int, required=True)
    parser.add_argument("--warning-triangles", type=int, required=True)
    parser.add_argument("--critical-triangles", type=int, required=True)
    return parser.parse_args(argv)


def main() -> int:
    argv = sys.argv
    script_args = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    args = parse_args(script_args)
    report = validate(args)
    Path(args.output_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
