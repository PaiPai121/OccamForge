from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Vector


for parent in Path(__file__).resolve().parents:
    if (parent / "assetforge").is_dir():
        sys.path.insert(0, str(parent))
        break

from assetforge.analysis.scale_analysis import (  # noqa: E402
    ScaleAnalysisMesh,
    analyze_scale_persistence,
    scale_analysis_report_dict,
)


SUPPORTED_EXTENSIONS = {".blend", ".obj", ".fbx", ".glb", ".gltf"}
BLUE_RED_COLORS: tuple[tuple[float, tuple[float, float, float, float]], ...] = (
    (0.00, (0.02, 0.12, 1.00, 1.0)),
    (0.35, (0.00, 0.75, 0.95, 1.0)),
    (0.55, (0.25, 0.85, 0.25, 1.0)),
    (0.75, (1.00, 0.82, 0.00, 1.0)),
    (1.00, (1.00, 0.08, 0.02, 1.0)),
)


def _clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def _import_source(source_file: Path) -> None:
    suffix = source_file.suffix.lower()
    if suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(source_file))
        return

    _clear_scene()
    if suffix == ".obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(filepath=str(source_file))
        else:
            bpy.ops.import_scene.obj(filepath=str(source_file))
    elif suffix == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(source_file))
    elif suffix in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(source_file))
    else:
        raise ValueError(f"Unsupported scale analysis source type: {source_file.suffix}")


def _mesh_objects() -> list[bpy.types.Object]:
    return [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]


def _select_object(target_name: str | None) -> bpy.types.Object | None:
    mesh_objects = _mesh_objects()
    if target_name:
        return next((obj for obj in mesh_objects if obj.name == target_name), None)
    return mesh_objects[0] if mesh_objects else None


def _isolate_target_for_render(target: bpy.types.Object) -> None:
    """Render only the analyzed object so unscored meshes do not appear as black/original material."""
    for obj in _mesh_objects():
        hidden = obj != target
        obj.hide_render = hidden
        obj.hide_viewport = hidden


def _parse_scales(scale_text: str | None, diagonal: float) -> list[float] | None:
    if not scale_text:
        return None
    scales: list[float] = []
    for item in scale_text.split(","):
        value = item.strip()
        if not value:
            continue
        if value.endswith("D"):
            scales.append(float(value[:-1]) * diagonal)
        else:
            scales.append(float(value))
    return scales


def _bbox_diagonal(obj: bpy.types.Object) -> float:
    points = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    mins = Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points)))
    maxs = Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points)))
    return float((maxs - mins).length)


def _to_scale_mesh(obj: bpy.types.Object) -> ScaleAnalysisMesh:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    try:
        mesh.calc_loop_triangles()
        vertices = [tuple(obj.matrix_world @ vertex.co) for vertex in mesh.vertices]
        triangles = [
            (int(triangle.vertices[0]), int(triangle.vertices[1]), int(triangle.vertices[2]))
            for triangle in mesh.loop_triangles
        ]
    finally:
        evaluated.to_mesh_clear()
    return ScaleAnalysisMesh(vertices=vertices, triangles=triangles, object_name=obj.name)


def _make_material(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = color
        bsdf.inputs["Roughness"].default_value = 0.55
    return material


def _make_emissive_material(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    material = _make_material(name, color)
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Emission Color"].default_value = color
        bsdf.inputs["Emission Strength"].default_value = 0.45
    return material


def _interpolate_color(value: float, invert: bool = False) -> tuple[float, float, float, float]:
    value = max(0.0, min(1.0, 1.0 - value if invert else value))
    for index, (stop, color) in enumerate(BLUE_RED_COLORS):
        if value <= stop:
            if index == 0:
                return color
            prev_stop, prev_color = BLUE_RED_COLORS[index - 1]
            span = max(stop - prev_stop, 1e-12)
            ratio = (value - prev_stop) / span
            return tuple(prev_color[channel] * (1.0 - ratio) + color[channel] * ratio for channel in range(4))  # type: ignore[return-value]
    return BLUE_RED_COLORS[-1][1]


def _assign_neutral_material(obj: bpy.types.Object) -> None:
    obj.data.materials.clear()
    obj.data.materials.append(_make_material("ScaleAnalysis_Neutral_Surface", (0.50, 0.54, 0.58, 1.0)))
    for polygon in obj.data.polygons:
        polygon.material_index = 0


def _score_edges(mesh: ScaleAnalysisMesh, scores: list[float]) -> list[dict[str, Any]]:
    edges: dict[tuple[int, int], dict[str, Any]] = {}
    for triangle in mesh.triangles:
        tri_edges = (
            tuple(sorted((triangle[0], triangle[1]))),
            tuple(sorted((triangle[1], triangle[2]))),
            tuple(sorted((triangle[2], triangle[0]))),
        )
        for v0_index, v1_index in tri_edges:
            if v0_index >= len(scores) or v1_index >= len(scores):
                continue
            score = max(float(scores[v0_index]), float(scores[v1_index]))
            existing = edges.get((v0_index, v1_index))
            if existing is not None:
                existing["score"] = max(float(existing["score"]), score)
                continue
            v0 = mesh.vertices[v0_index]
            v1 = mesh.vertices[v1_index]
            edges[(v0_index, v1_index)] = {
                "v0_position": [float(v0[0]), float(v0[1]), float(v0[2])],
                "v1_position": [float(v1[0]), float(v1[1]), float(v1[2])],
                "score": score,
            }
    return list(edges.values())


def _remove_scale_edge_overlays() -> None:
    for obj in list(bpy.context.scene.objects):
        if obj.name.startswith("ScaleEdge_"):
            bpy.data.objects.remove(obj, do_unlink=True)


def _render_edge_heatmap(
    obj: bpy.types.Object,
    mesh: ScaleAnalysisMesh,
    scores: list[float],
    prefix: str,
    invert: bool = False,
) -> None:
    _remove_scale_edge_overlays()
    _assign_neutral_material(obj)
    edges = _score_edges(mesh, scores)
    if not edges:
        return

    mins, maxs = _collect_bounds([obj])
    diagonal = max(float((maxs - mins).length), 1.0)
    bevel_depth = max(diagonal * 0.0009, 0.0003)
    bins = [
        ("Blue_Low", 0.20, _interpolate_color(0.10, invert)),
        ("Cyan", 0.40, _interpolate_color(0.30, invert)),
        ("Green", 0.60, _interpolate_color(0.50, invert)),
        ("Yellow", 0.80, _interpolate_color(0.75, invert)),
        ("Red_High", 1.01, _interpolate_color(0.95, invert)),
    ]
    grouped: list[list[dict[str, Any]]] = [[] for _ in bins]
    for edge in edges:
        value = max(0.0, min(1.0, float(edge["score"])))
        for index, (_, upper, _) in enumerate(bins):
            if value <= upper:
                grouped[index].append(edge)
                break

    for index, (name, _, color) in enumerate(bins):
        if not grouped[index]:
            continue
        curve = bpy.data.curves.new(f"ScaleEdge_{prefix}_{name}", type="CURVE")
        curve.dimensions = "3D"
        curve.resolution_u = 1
        curve.bevel_depth = bevel_depth
        curve.bevel_resolution = 1
        for edge in grouped[index]:
            spline = curve.splines.new("POLY")
            spline.points.add(1)
            v0 = edge["v0_position"]
            v1 = edge["v1_position"]
            spline.points[0].co = (v0[0], v0[1], v0[2], 1.0)
            spline.points[1].co = (v1[0], v1[1], v1[2], 1.0)
        overlay = bpy.data.objects.new(f"ScaleEdge_{prefix}_{name}", curve)
        bpy.context.collection.objects.link(overlay)
        overlay.data.materials.append(_make_emissive_material(f"ScaleEdge_{prefix}_{name}_Material", color))


def _collect_bounds(mesh_objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    mins = Vector((math.inf, math.inf, math.inf))
    maxs = Vector((-math.inf, -math.inf, -math.inf))
    for obj in mesh_objects:
        for corner in obj.bound_box:
            point = obj.matrix_world @ Vector(corner)
            mins.x = min(mins.x, point.x)
            mins.y = min(mins.y, point.y)
            mins.z = min(mins.z, point.z)
            maxs.x = max(maxs.x, point.x)
            maxs.y = max(maxs.y, point.y)
            maxs.z = max(maxs.z, point.z)
    if math.isinf(mins.x):
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    return mins, maxs


def _look_at(obj: bpy.types.Object, target: Vector) -> None:
    direction = target - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def _setup_camera_and_light(mesh_objects: list[bpy.types.Object]) -> None:
    mins, maxs = _collect_bounds(mesh_objects)
    center = (mins + maxs) * 0.5
    size = maxs - mins
    diagonal = max(float(size.length), 1.0)

    camera_data = bpy.data.cameras.new("Scale_Analysis_Camera")
    camera = bpy.data.objects.new("Scale_Analysis_Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = center + Vector((diagonal * 0.85, -diagonal * 1.65, diagonal * 0.8))
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = max(size.x * 0.85 + size.z * 0.55, size.y * 0.45 + size.z * 0.9, 1.0) * 1.2
    _look_at(camera, center)
    bpy.context.scene.camera = camera

    light_data = bpy.data.lights.new("Scale_Analysis_Light", type="AREA")
    light = bpy.data.objects.new("Scale_Analysis_Light", light_data)
    bpy.context.collection.objects.link(light)
    light.location = center + Vector((0.0, -diagonal * 1.1, diagonal * 1.25))
    light_data.energy = 500.0
    light_data.size = max(diagonal, 1.0)


def _render(output_path: Path) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in {item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items} else "BLENDER_EEVEE"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 1000
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output_path)
    bpy.ops.render.render(write_still=False)
    bpy.data.images["Render Result"].save_render(filepath=str(output_path))


def generate(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source_file).resolve()
    output_directory = Path(args.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    mean_curvature_path = output_directory / "mean_curvature_heatmap.png"
    mean_curvature_inverse_path = output_directory / "mean_curvature_heatmap_inverse.png"
    center_surround_path = output_directory / "center_surround_heatmap.png"
    center_surround_inverse_path = output_directory / "center_surround_heatmap_inverse.png"
    persistence_path = output_directory / "scale_persistence_heatmap.png"
    persistence_inverse_path = output_directory / "scale_persistence_heatmap_inverse.png"
    tiny_path = output_directory / "tiny_detail_heatmap.png"
    tiny_inverse_path = output_directory / "tiny_detail_heatmap_inverse.png"

    if not source.exists():
        return {"input": str(source), "errors": [f"Input file does not exist: {source}"]}
    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return {"input": str(source), "errors": [f"Unsupported source type: {source.suffix}"]}

    _import_source(source)
    target = _select_object(args.object_name)
    if target is None:
        return {"input": str(source), "errors": ["No mesh object was found."]}

    mesh = _to_scale_mesh(target)
    scales = _parse_scales(args.scales, _bbox_diagonal(target))
    result = analyze_scale_persistence(mesh, scales=scales)

    if args.generate_heatmap:
        _isolate_target_for_render(target)
        _setup_camera_and_light([target])
        _render_edge_heatmap(target, mesh, result.mean_curvature, "NormalVariation")
        _render(mean_curvature_path)
        _render_edge_heatmap(target, mesh, result.mean_curvature, "NormalVariationInverse", invert=True)
        _render(mean_curvature_inverse_path)
        _render_edge_heatmap(target, mesh, result.center_surround_response, "CenterSurround")
        _render(center_surround_path)
        _render_edge_heatmap(target, mesh, result.center_surround_response, "CenterSurroundInverse", invert=True)
        _render(center_surround_inverse_path)
        _render_edge_heatmap(target, mesh, result.scale_persistence, "ScalePersistence")
        _render(persistence_path)
        _render_edge_heatmap(target, mesh, result.scale_persistence, "ScalePersistenceInverse", invert=True)
        _render(persistence_inverse_path)
        _render_edge_heatmap(target, mesh, result.tiny_detail_score, "TinyDetail")
        _render(tiny_path)
        _render_edge_heatmap(target, mesh, result.tiny_detail_score, "TinyDetailInverse", invert=True)
        _render(tiny_inverse_path)

    report = scale_analysis_report_dict(
        result,
        input_path=str(source),
        output_directory=str(output_directory),
        persistence_heatmap=str(persistence_path),
        tiny_detail_heatmap=str(tiny_path),
        mean_curvature_heatmap=str(mean_curvature_path),
        center_surround_heatmap=str(center_surround_path),
    )
    report["mean_curvature_heatmap_inverse"] = str(mean_curvature_inverse_path)
    report["center_surround_heatmap_inverse"] = str(center_surround_inverse_path)
    report["scale_persistence_heatmap_inverse"] = str(persistence_inverse_path)
    report["tiny_detail_heatmap_inverse"] = str(tiny_inverse_path)
    report["generate_heatmap"] = bool(args.generate_heatmap)
    report["heatmap_rendering"] = "edge_overlay_from_vertex_scores"
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Scale Analysis V0 heatmaps.")
    parser.add_argument("--source-file", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--object-name")
    parser.add_argument("--scales", help="Comma-separated absolute scales, or fractions suffixed with D, e.g. 0.005D,0.01D.")
    parser.add_argument("--generate-heatmap", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    report = generate(args)
    Path(args.output_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if not report.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]))
