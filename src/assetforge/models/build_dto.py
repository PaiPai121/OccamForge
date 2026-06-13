from __future__ import annotations

from pathlib import Path
from typing import Any

from assetforge.domain.build import CitiesSkylinesBuildReport


def build_report_from_dict(payload: dict[str, Any]) -> CitiesSkylinesBuildReport:
    return CitiesSkylinesBuildReport(
        source_blend_file=Path(payload["source_blend_file"]),
        build_folder=Path(payload["build_folder"]),
        working_blend_file=Path(payload["working_blend_file"]),
        fbx_file=Path(payload["fbx_file"]),
        diffuse_texture_file=Path(payload["diffuse_texture_file"]),
        report_file=Path(payload["report_file"]),
        profile_id=str(payload["profile_id"]),
        original_triangle_count=int(payload["original_triangle_count"]),
        final_triangle_count=int(payload["final_triangle_count"]),
        target_triangle_count=int(payload["target_triangle_count"]),
        optimized=bool(payload["optimized"]),
        body_object=payload.get("body_object"),
        wheel_count=int(payload["wheel_count"]),
        object_count=int(payload["object_count"]),
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
        errors=tuple(str(item) for item in payload.get("errors", [])),
    )


def build_report_to_dict(report: CitiesSkylinesBuildReport) -> dict[str, Any]:
    return {
        "source_blend_file": str(report.source_blend_file),
        "build_folder": str(report.build_folder),
        "working_blend_file": str(report.working_blend_file),
        "fbx_file": str(report.fbx_file),
        "diffuse_texture_file": str(report.diffuse_texture_file),
        "report_file": str(report.report_file),
        "profile_id": report.profile_id,
        "original_triangle_count": report.original_triangle_count,
        "final_triangle_count": report.final_triangle_count,
        "target_triangle_count": report.target_triangle_count,
        "optimized": report.optimized,
        "body_object": report.body_object,
        "wheel_count": report.wheel_count,
        "object_count": report.object_count,
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }

