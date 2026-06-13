from __future__ import annotations

from pathlib import Path
from typing import Any

from assetforge.domain.analysis import VehicleAnalysisReport, VehicleObjectSummary


def report_from_dict(payload: dict[str, Any]) -> VehicleAnalysisReport:
    objects = tuple(
        VehicleObjectSummary(
            name=str(item["name"]),
            vertex_count=int(item["vertex_count"]),
            triangle_count=int(item["triangle_count"]),
            is_body=bool(item.get("is_body", False)),
            is_wheel=bool(item.get("is_wheel", False)),
        )
        for item in payload.get("objects", [])
    )

    return VehicleAnalysisReport(
        blend_file=Path(payload["blend_file"]),
        has_vehicle_body=bool(payload.get("has_vehicle_body", False)),
        wheel_count=int(payload.get("wheel_count", 0)),
        object_count=int(payload.get("object_count", 0)),
        vertex_count=int(payload.get("vertex_count", 0)),
        triangle_count=int(payload.get("triangle_count", 0)),
        objects=objects,
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
        errors=tuple(str(item) for item in payload.get("errors", [])),
    )


def report_to_dict(report: VehicleAnalysisReport) -> dict[str, Any]:
    return {
        "blend_file": str(report.blend_file),
        "has_vehicle_body": report.has_vehicle_body,
        "wheel_count": report.wheel_count,
        "object_count": report.object_count,
        "vertex_count": report.vertex_count,
        "triangle_count": report.triangle_count,
        "objects": [
            {
                "name": item.name,
                "vertex_count": item.vertex_count,
                "triangle_count": item.triangle_count,
                "is_body": item.is_body,
                "is_wheel": item.is_wheel,
            }
            for item in report.objects
        ],
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }

