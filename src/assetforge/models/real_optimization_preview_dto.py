from __future__ import annotations

from pathlib import Path
from typing import Any

from assetforge.domain.real_optimization_preview import (
    RealOptimizationPreviewItem,
    RealOptimizationPreviewReport,
)


def real_preview_item_from_dict(payload: dict[str, Any]) -> RealOptimizationPreviewItem:
    return RealOptimizationPreviewItem(
        target_triangles=int(payload["target_triangles"]),
        actual_triangles=int(payload["actual_triangles"]),
        reduction_percent=float(payload["reduction_percent"]),
        compatibility_score=int(payload["compatibility_score"]),
        rating=str(payload["rating"]),
        preview_blend_path=Path(payload["preview_blend_path"]),
        preview_image_path=Path(payload["preview_image_path"]),
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
        errors=tuple(str(item) for item in payload.get("errors", [])),
    )


def real_preview_item_to_dict(item: RealOptimizationPreviewItem) -> dict[str, Any]:
    return {
        "target_triangles": item.target_triangles,
        "actual_triangles": item.actual_triangles,
        "reduction_percent": item.reduction_percent,
        "compatibility_score": item.compatibility_score,
        "rating": item.rating,
        "preview_blend_path": str(item.preview_blend_path),
        "preview_image_path": str(item.preview_image_path),
        "warnings": list(item.warnings),
        "errors": list(item.errors),
    }


def real_preview_report_from_dict(payload: dict[str, Any]) -> RealOptimizationPreviewReport:
    return RealOptimizationPreviewReport(
        source_blend_file=Path(payload["source_blend_file"]),
        output_directory=Path(payload["output_directory"]),
        original_triangle_count=int(payload["original_triangle_count"]),
        profile_id=str(payload["profile_id"]),
        items=tuple(real_preview_item_from_dict(item) for item in payload.get("items", [])),
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
        errors=tuple(str(item) for item in payload.get("errors", [])),
    )


def real_preview_report_to_dict(report: RealOptimizationPreviewReport) -> dict[str, Any]:
    return {
        "source_blend_file": str(report.source_blend_file),
        "output_directory": str(report.output_directory),
        "original_triangle_count": report.original_triangle_count,
        "profile_id": report.profile_id,
        "items": [real_preview_item_to_dict(item) for item in report.items],
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }
