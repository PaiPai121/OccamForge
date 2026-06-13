from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fbx", required=True)
    parser.add_argument("--output-json", required=True)
    argv = sys.argv
    script_args = argv[argv.index("--") + 1 :] if "--" in argv else argv[1:]
    args = parser.parse_args(script_args)

    fbx_file = Path(args.fbx)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.ops.import_scene.fbx(filepath=str(fbx_file))

    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    material_count = sum(len(obj.data.materials) for obj in mesh_objects)
    payload = {
        "fbx_file": str(fbx_file),
        "imported": len(mesh_objects) > 0,
        "mesh_object_count": len(mesh_objects),
        "material_slot_count": material_count,
        "object_names": [obj.name for obj in mesh_objects],
    }
    Path(args.output_json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return 0 if payload["imported"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
