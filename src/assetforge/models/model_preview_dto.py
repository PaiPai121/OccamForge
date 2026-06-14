from __future__ import annotations

from pathlib import Path
from typing import Any

from assetforge.domain.model_preview import ModelPreviewReport


def model_preview_report_from_dict(payload: dict[str, Any]) -> ModelPreviewReport:
    return ModelPreviewReport(
        blend_file=Path(payload["blend_file"]),
        preview_image_path=Path(payload["preview_image_path"]),
        triangle_count=int(payload["triangle_count"]),
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
        errors=tuple(str(item) for item in payload.get("errors", [])),
    )


def model_preview_report_to_dict(report: ModelPreviewReport) -> dict[str, Any]:
    return {
        "blend_file": str(report.blend_file),
        "preview_image_path": str(report.preview_image_path),
        "triangle_count": report.triangle_count,
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }
