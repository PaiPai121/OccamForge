from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import bpy

sys.path.insert(0, str(Path(__file__).parent))

from generate_real_optimization_preview import _configure_render, _setup_camera_and_light
from optimize_vehicle import _count_scene_triangles, _mesh_objects


def generate(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.blend_file)
    output_directory = Path(args.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    preview_image = output_directory / f"{source.stem}_source_preview.png"
    warnings: list[str] = []
    errors: list[str] = []

    if not source.exists():
        return {
            "blend_file": str(source),
            "preview_image_path": str(preview_image),
            "triangle_count": 0,
            "warnings": [],
            "errors": [f"Blend file does not exist: {source}"],
        }

    bpy.ops.wm.open_mainfile(filepath=str(source))
    mesh_objects = _mesh_objects()
    triangle_count = _count_scene_triangles(mesh_objects)
    if not mesh_objects:
        errors.append("No mesh objects were found.")
    else:
        _setup_camera_and_light(mesh_objects)
        _configure_render(preview_image)
        bpy.ops.render.render(write_still=False)
        bpy.data.images["Render Result"].save_render(filepath=str(preview_image))

    return {
        "blend_file": str(source),
        "preview_image_path": str(preview_image),
        "triangle_count": triangle_count,
        "warnings": warnings,
        "errors": errors,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate an AssetForge source model preview.")
    parser.add_argument("--blend-file", required=True)
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
