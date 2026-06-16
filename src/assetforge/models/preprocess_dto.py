from __future__ import annotations

from pathlib import Path
from typing import Any

from assetforge.domain.preprocess import PreprocessReport


def preprocess_report_from_dict(payload: dict[str, Any]) -> PreprocessReport:
    return PreprocessReport(
        source_blend_file=Path(payload["source_blend_file"]),
        preprocessed_blend_file=Path(payload["preprocessed_blend_file"]),
        report_file=Path(payload["report_file"]),
        original_triangle_count=int(payload.get("original_triangle_count", 0)),
        preprocessed_triangle_count=int(payload.get("preprocessed_triangle_count", 0)),
        removed_triangle_count=int(payload.get("removed_triangle_count", 0)),
        reduction_percentage=float(payload.get("reduction_percentage", 0.0)),
        limited_dissolve_angle_degrees=float(
            payload.get("limited_dissolve_angle_degrees", 0.0)
        ),
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
        errors=tuple(str(item) for item in payload.get("errors", [])),
    )


def preprocess_report_to_dict(report: PreprocessReport) -> dict[str, Any]:
    return {
        "source_blend_file": str(report.source_blend_file),
        "preprocessed_blend_file": str(report.preprocessed_blend_file),
        "report_file": str(report.report_file),
        "original_triangle_count": report.original_triangle_count,
        "preprocessed_triangle_count": report.preprocessed_triangle_count,
        "removed_triangle_count": report.removed_triangle_count,
        "reduction_percentage": report.reduction_percentage,
        "limited_dissolve_angle_degrees": report.limited_dissolve_angle_degrees,
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }
