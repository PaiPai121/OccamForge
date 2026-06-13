from __future__ import annotations

from pathlib import Path
from typing import Any

from assetforge.domain.validation import ImportReadiness, ValidationIssue, ValidationReport


def validation_report_from_dict(payload: dict[str, Any]) -> ValidationReport:
    issues = tuple(
        ValidationIssue(
            check=str(item["check"]),
            severity=str(item["severity"]),
            message=str(item["message"]),
        )
        for item in payload.get("issues", [])
    )
    blender_path = payload.get("blender_path")
    readiness_payload = payload["import_readiness"]
    import_readiness = ImportReadiness(
        package_folder=Path(readiness_payload["package_folder"]),
        fbx_file=Path(readiness_payload["fbx_file"]),
        diffuse_texture_file=Path(readiness_payload["diffuse_texture_file"]),
        build_report_file=Path(readiness_payload["build_report_file"]),
        files_ready=bool(readiness_payload["files_ready"]),
        blender_fbx_import_ready=bool(readiness_payload["blender_fbx_import_ready"]),
        import_ready=bool(readiness_payload["import_ready"]),
        cities_skylines_editor_status=str(readiness_payload["cities_skylines_editor_status"]),
        manual_steps=tuple(str(item) for item in readiness_payload.get("manual_steps", [])),
    )
    return ValidationReport(
        blend_file=Path(payload["blend_file"]),
        report_file=Path(payload["report_file"]),
        profile_id=str(payload["profile_id"]),
        triangle_count=int(payload["triangle_count"]),
        wheel_count=int(payload["wheel_count"]),
        object_count=int(payload["object_count"]),
        blender_path=Path(blender_path) if blender_path else None,
        body_object=payload.get("body_object"),
        wheel_objects=tuple(str(item) for item in payload.get("wheel_objects", [])),
        unknown_objects=tuple(str(item) for item in payload.get("unknown_objects", [])),
        unapplied_transform_objects=tuple(
            str(item) for item in payload.get("unapplied_transform_objects", [])
        ),
        auto_texture_candidate_objects=tuple(
            str(item) for item in payload.get("auto_texture_candidate_objects", [])
        ),
        missing_lods=tuple(str(item) for item in payload.get("missing_lods", [])),
        score=int(payload["score"]),
        rating=str(payload["rating"]),
        export_ready=bool(payload["export_ready"]),
        import_readiness=import_readiness,
        issues=issues,
        messages=tuple(str(item) for item in payload.get("messages", [])),
    )


def validation_report_to_dict(report: ValidationReport) -> dict[str, Any]:
    return {
        "blend_file": str(report.blend_file),
        "report_file": str(report.report_file),
        "profile_id": report.profile_id,
        "triangle_count": report.triangle_count,
        "wheel_count": report.wheel_count,
        "object_count": report.object_count,
        "blender_path": str(report.blender_path) if report.blender_path else None,
        "body_object": report.body_object,
        "wheel_objects": list(report.wheel_objects),
        "unknown_objects": list(report.unknown_objects),
        "unapplied_transform_objects": list(report.unapplied_transform_objects),
        "auto_texture_candidate_objects": list(report.auto_texture_candidate_objects),
        "missing_lods": list(report.missing_lods),
        "score": report.score,
        "rating": report.rating,
        "export_ready": report.export_ready,
        "import_readiness": {
            "package_folder": str(report.import_readiness.package_folder),
            "fbx_file": str(report.import_readiness.fbx_file),
            "diffuse_texture_file": str(report.import_readiness.diffuse_texture_file),
            "build_report_file": str(report.import_readiness.build_report_file),
            "files_ready": report.import_readiness.files_ready,
            "blender_fbx_import_ready": report.import_readiness.blender_fbx_import_ready,
            "import_ready": report.import_readiness.import_ready,
            "cities_skylines_editor_status": report.import_readiness.cities_skylines_editor_status,
            "manual_steps": list(report.import_readiness.manual_steps),
        },
        "issues": [
            {"check": issue.check, "severity": issue.severity, "message": issue.message}
            for issue in report.issues
        ],
        "messages": list(report.messages),
    }
