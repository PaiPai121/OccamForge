from __future__ import annotations

from pathlib import Path
from typing import Any

from assetforge.domain.simplification_report import (
    SimplificationRegion,
    SimplificationReport,
)


def simplification_region_from_dict(payload: dict[str, Any]) -> SimplificationRegion:
    return SimplificationRegion(
        region_id=str(payload.get("region_id", "")),
        object_name=str(payload.get("object_name", "")),
        original_triangles=int(payload.get("original_triangles", 0)),
        optimized_triangles=int(payload.get("optimized_triangles", 0)),
        removed_triangles=int(payload.get("removed_triangles", 0)),
        reduction_percentage=float(payload.get("reduction_percentage", 0.0)),
    )


def simplification_region_to_dict(region: SimplificationRegion) -> dict[str, Any]:
    return {
        "region_id": region.region_id,
        "object_name": region.object_name,
        "original_triangles": region.original_triangles,
        "optimized_triangles": region.optimized_triangles,
        "removed_triangles": region.removed_triangles,
        "reduction_percentage": region.reduction_percentage,
    }


def simplification_report_from_dict(payload: dict[str, Any]) -> SimplificationReport:
    return SimplificationReport(
        source_blend_file=Path(payload["source_blend_file"]),
        optimized_blend_file=Path(payload["optimized_blend_file"]),
        report_json_path=Path(payload["report_json_path"]),
        heatmap_image_path=Path(payload["heatmap_image_path"]),
        original_triangle_count=int(payload.get("original_triangle_count", 0)),
        optimized_triangle_count=int(payload.get("optimized_triangle_count", 0)),
        removed_triangle_count=int(payload.get("removed_triangle_count", 0)),
        reduction_percentage=float(payload.get("reduction_percentage", 0.0)),
        regions=tuple(
            simplification_region_from_dict(item)
            for item in payload.get("regions", [])
        ),
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
        errors=tuple(str(item) for item in payload.get("errors", [])),
    )


def simplification_report_to_dict(report: SimplificationReport) -> dict[str, Any]:
    return {
        "source_blend_file": str(report.source_blend_file),
        "optimized_blend_file": str(report.optimized_blend_file),
        "report_json_path": str(report.report_json_path),
        "heatmap_image_path": str(report.heatmap_image_path),
        "original_triangle_count": report.original_triangle_count,
        "optimized_triangle_count": report.optimized_triangle_count,
        "removed_triangle_count": report.removed_triangle_count,
        "reduction_percentage": report.reduction_percentage,
        "regions": [
            simplification_region_to_dict(region)
            for region in report.regions
        ],
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }
