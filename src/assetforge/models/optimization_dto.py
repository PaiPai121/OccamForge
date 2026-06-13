from __future__ import annotations

from pathlib import Path
from typing import Any

from assetforge.domain.optimization import VehicleOptimizationReport


def optimization_report_from_dict(payload: dict[str, Any]) -> VehicleOptimizationReport:
    return VehicleOptimizationReport(
        source_blend_file=Path(payload["source_blend_file"]),
        optimized_blend_file=Path(payload["optimized_blend_file"]),
        report_file=Path(payload["report_file"]),
        profile_id=str(payload["profile_id"]),
        target_triangle_count=int(payload["target_triangle_count"]),
        original_triangle_count=int(payload["original_triangle_count"]),
        optimized_triangle_count=int(payload["optimized_triangle_count"]),
        reduction_percentage=float(payload["reduction_percentage"]),
        body_object=payload.get("body_object"),
        wheel_count=int(payload.get("wheel_count", 0)),
        decimate_ratio=float(payload.get("decimate_ratio", 1.0)),
        iterations=int(payload.get("iterations", 0)),
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
        errors=tuple(str(item) for item in payload.get("errors", [])),
    )


def optimization_report_to_dict(report: VehicleOptimizationReport) -> dict[str, Any]:
    return {
        "source_blend_file": str(report.source_blend_file),
        "optimized_blend_file": str(report.optimized_blend_file),
        "report_file": str(report.report_file),
        "profile_id": report.profile_id,
        "target_triangle_count": report.target_triangle_count,
        "original_triangle_count": report.original_triangle_count,
        "optimized_triangle_count": report.optimized_triangle_count,
        "reduction_percentage": report.reduction_percentage,
        "body_object": report.body_object,
        "wheel_count": report.wheel_count,
        "decimate_ratio": report.decimate_ratio,
        "iterations": report.iterations,
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }
