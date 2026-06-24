from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
for parent in Path(__file__).resolve().parents:
    if (parent / "assetforge").is_dir():
        sys.path.insert(0, str(parent))
        break

from assetforge.analysis.scale_analysis import analyze_scale_persistence  # noqa: E402
from generate_qem_heatmap import (  # noqa: E402
    _apply_cost_visualization,
    _collect_qem_data,
    _cost_statistics,
    _import_source,
    _mesh_objects,
    _render_heatmap,
)
from generate_scale_analysis import _bbox_diagonal, _parse_scales, _select_object, _to_scale_mesh  # noqa: E402


SUPPORTED_EXTENSIONS = {".blend", ".obj", ".fbx", ".glb", ".gltf"}
BASE_QEM_FORMULA = "normalize(-log(eps + QEM))"


CANDIDATE_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("AFCost_00", f"{BASE_QEM_FORMULA}"),
    ("AFCost_01", f"{BASE_QEM_FORMULA} * (1 + lambda * P)"),
    ("AFCost_02", f"{BASE_QEM_FORMULA} * (1 + lambda * InvD)"),
    ("AFCost_03", f"{BASE_QEM_FORMULA} * (1 + lambda * P * InvD)"),
    ("AFCost_04", f"{BASE_QEM_FORMULA} * (1 - lambda * D)"),
    ("AFCost_05", f"{BASE_QEM_FORMULA} * (1 - lambda * InvP)"),
    ("AFCost_06", f"{BASE_QEM_FORMULA} * (1 - lambda * D * InvP)"),
    ("AFCost_07", f"{BASE_QEM_FORMULA} * normalize(P / (D + eps))"),
    ("AFCost_08", f"{BASE_QEM_FORMULA} * normalize(D / (P + eps))"),
    ("AFCost_09", f"{BASE_QEM_FORMULA} * normalize(P - D)"),
    ("AFCost_10", f"{BASE_QEM_FORMULA} * normalize(D - P)"),
    ("AFCost_11", f"{BASE_QEM_FORMULA} * normalize(P * InvD)"),
)


def _emit_progress(percent: int, stage: str) -> None:
    print(
        "ASSETFORGE_PROGRESS "
        + json.dumps(
            {
                "kind": "afcost_candidates",
                "percent": max(0, min(100, int(percent))),
                "stage": stage,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def _normalize(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    low = min(values)
    high = max(values)
    if high - low <= 1e-12:
        return [0.0 for _ in values]
    return [(value - low) / (high - low) for value in values]


def _rank_display(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    if len(values) == 1:
        return [0.0]
    ordered = sorted(values)
    return [
        max(0.0, min(1.0, (bisect.bisect_right(ordered, value) - 1) / (len(ordered) - 1)))
        for value in values
    ]


def _stats(values: Sequence[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0}
    ordered = sorted(values)

    def percentile(pct: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        position = (len(ordered) - 1) * pct / 100.0
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return ordered[lower]
        weight = position - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "p25": percentile(25.0),
        "p50": percentile(50.0),
        "p75": percentile(75.0),
    }


def _qem_base_values(qem: Sequence[float], eps: float) -> list[float]:
    return _normalize([-math.log(max(eps + value, eps)) for value in qem])


def _candidate_values(qem_base: list[float], p: list[float], d: list[float], lambda_value: float, eps: float) -> dict[str, list[float]]:
    inv_p = [1.0 - value for value in p]
    inv_d = [1.0 - value for value in d]
    p_over_d = _normalize([p_value / (d_value + eps) for p_value, d_value in zip(p, d, strict=False)])
    d_over_p = _normalize([d_value / (p_value + eps) for p_value, d_value in zip(p, d, strict=False)])
    p_minus_d = _normalize([p_value - d_value for p_value, d_value in zip(p, d, strict=False)])
    d_minus_p = _normalize([d_value - p_value for p_value, d_value in zip(p, d, strict=False)])
    protected_low_detail = _normalize([
        p_value * inv_d_value
        for p_value, inv_d_value in zip(p, inv_d, strict=False)
    ])

    return {
        "AFCost_00": qem_base,
        "AFCost_01": [q * (1.0 + lambda_value * p_value) for q, p_value in zip(qem_base, p, strict=False)],
        "AFCost_02": [q * (1.0 + lambda_value * inv_d_value) for q, inv_d_value in zip(qem_base, inv_d, strict=False)],
        "AFCost_03": [q * (1.0 + lambda_value * p_value * inv_d_value) for q, p_value, inv_d_value in zip(qem_base, p, inv_d, strict=False)],
        "AFCost_04": [q * max(0.0, 1.0 - lambda_value * d_value) for q, d_value in zip(qem_base, d, strict=False)],
        "AFCost_05": [q * max(0.0, 1.0 - lambda_value * inv_p_value) for q, inv_p_value in zip(qem_base, inv_p, strict=False)],
        "AFCost_06": [q * max(0.0, 1.0 - lambda_value * d_value * inv_p_value) for q, d_value, inv_p_value in zip(qem_base, d, inv_p, strict=False)],
        "AFCost_07": [q * factor for q, factor in zip(qem_base, p_over_d, strict=False)],
        "AFCost_08": [q * factor for q, factor in zip(qem_base, d_over_p, strict=False)],
        "AFCost_09": [q * factor for q, factor in zip(qem_base, p_minus_d, strict=False)],
        "AFCost_10": [q * factor for q, factor in zip(qem_base, d_minus_p, strict=False)],
        "AFCost_11": [q * factor for q, factor in zip(qem_base, protected_low_detail, strict=False)],
    }


def _render_candidate(edges: list[dict[str, Any]], name: str, values: list[float], output_path: Path) -> None:
    display_values = _rank_display(values)
    for edge, value, display_value in zip(edges, values, display_values, strict=False):
        edge[f"{name}_value"] = float(value)
        edge[f"{name}_display_heat"] = float(display_value)
    _render_heatmap(edges, output_path, f"{name}_display_heat")


def generate(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source_file).resolve()
    output_directory = Path(args.output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        return {"input": str(source), "errors": [f"Input file does not exist: {source}"]}
    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return {"input": str(source), "errors": [f"Unsupported source type: {source.suffix}"]}

    _emit_progress(5, "Importing source model")
    _import_source(source)
    target = _select_object(args.object_name)
    if target is None:
        return {"input": str(source), "errors": ["No mesh object was found."]}
    target_name = str(target.name)

    _emit_progress(20, "Computing scale persistence and tiny detail")
    mesh = _to_scale_mesh(target)
    scale_result = analyze_scale_persistence(mesh, scales=_parse_scales(args.scales, _bbox_diagonal(target)))
    _emit_progress(40, "Collecting QEM edge costs")
    all_edges, metadata = _collect_qem_data([target])
    if not all_edges:
        return {"input": str(source), "object_name": target.name, "errors": ["No mesh edges were found."]}
    qem_min_max = _apply_cost_visualization(all_edges, "cost", "heat", "display_heat", "color_rgb")
    qem_stats = _cost_statistics(all_edges, qem_min_max, "cost")

    _emit_progress(55, "Projecting parent signals onto edges")
    qem_values: list[float] = []
    persistence_values: list[float] = []
    tiny_values: list[float] = []
    for edge in all_edges:
        v0 = int(edge["v0"])
        v1 = int(edge["v1"])
        qem_values.append(float(edge["cost"]))
        persistence_values.append(max(scale_result.scale_persistence[v0], scale_result.scale_persistence[v1]))
        tiny_values.append(max(scale_result.tiny_detail_score[v0], scale_result.tiny_detail_score[v1]))

    qem_base_values = _qem_base_values(qem_values, float(args.eps))
    candidate_values = _candidate_values(
        qem_base_values,
        persistence_values,
        tiny_values,
        float(args.lambda_value),
        float(args.eps),
    )
    candidates: list[dict[str, Any]] = []
    formulas = dict(CANDIDATE_DEFINITIONS)
    for index, (name, _) in enumerate(CANDIDATE_DEFINITIONS, start=1):
        _emit_progress(
            55 + round((index - 1) / max(len(CANDIDATE_DEFINITIONS), 1) * 40),
            f"Rendering {name}",
        )
        output_path = output_directory / f"{name}.png"
        values = candidate_values[name]
        _render_candidate(all_edges, name, values, output_path)
        candidates.append(
            {
                "name": name,
                "formula": formulas[name],
                "heatmap_png": str(output_path),
                "stats": _stats(values),
            }
        )

    report = {
        "input": str(source),
        "object_name": target_name,
        "output_directory": str(output_directory),
        "vertex_count": scale_result.vertex_count,
        "triangle_count": scale_result.triangle_count,
        "edge_count": len(all_edges),
        "bbox_diagonal": scale_result.bbox_diagonal,
        "lambda": float(args.lambda_value),
        "eps": float(args.eps),
        "qem_base_formula": BASE_QEM_FORMULA,
        "edge_projection": {
            "P_edge": "max(P(u), P(v))",
            "D_edge": "max(D(u), D(v))",
            "InvP_edge": "1 - P_edge",
            "InvD_edge": "1 - D_edge",
        },
        "qem_stats": qem_stats,
        "qem_base_stats": _stats(qem_base_values),
        "persistence_edge_stats": _stats(persistence_values),
        "tiny_detail_edge_stats": _stats(tiny_values),
        "candidate_count": len(candidates),
        "candidates": candidates,
        "metadata": metadata,
        "errors": scale_result.errors,
    }
    (output_directory / "afcost_candidates_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    _emit_progress(100, "AF cost candidates complete")
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate AF cost combination candidate heatmaps.")
    parser.add_argument("--source-file", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--object-name")
    parser.add_argument("--scales", help="Comma-separated absolute scales, or fractions suffixed with D, e.g. 0.005D,0.01D.")
    parser.add_argument("--lambda-value", type=float, default=1.0)
    parser.add_argument("--eps", type=float, default=1e-6)
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
