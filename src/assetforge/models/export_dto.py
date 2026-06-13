from __future__ import annotations

from pathlib import Path
from typing import Any

from assetforge.domain.export import VehicleExportReport


def export_report_from_dict(payload: dict[str, Any]) -> VehicleExportReport:
    return VehicleExportReport(
        source_blend_file=Path(payload["source_blend_file"]),
        export_blend_file=Path(payload["export_blend_file"]),
        fbx_file=Path(payload["fbx_file"]),
        profile_id=str(payload["profile_id"]),
        triangle_count=int(payload["triangle_count"]),
        wheel_count=int(payload["wheel_count"]),
        object_count=int(payload["object_count"]),
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
        errors=tuple(str(item) for item in payload.get("errors", [])),
    )


def export_report_to_dict(report: VehicleExportReport) -> dict[str, Any]:
    return {
        "source_blend_file": str(report.source_blend_file),
        "export_blend_file": str(report.export_blend_file),
        "fbx_file": str(report.fbx_file),
        "profile_id": report.profile_id,
        "triangle_count": report.triangle_count,
        "wheel_count": report.wheel_count,
        "object_count": report.object_count,
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }

