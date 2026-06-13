from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    check: str
    severity: str
    message: str


@dataclass(frozen=True, slots=True)
class ImportReadiness:
    package_folder: Path
    fbx_file: Path
    diffuse_texture_file: Path
    build_report_file: Path
    files_ready: bool
    blender_fbx_import_ready: bool
    import_ready: bool
    cities_skylines_editor_status: str
    manual_steps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Game-readiness summary for a vehicle asset."""

    blend_file: Path
    report_file: Path
    profile_id: str
    triangle_count: int
    wheel_count: int
    object_count: int
    blender_path: Path | None
    body_object: str | None
    wheel_objects: tuple[str, ...]
    unknown_objects: tuple[str, ...]
    unapplied_transform_objects: tuple[str, ...]
    auto_texture_candidate_objects: tuple[str, ...]
    missing_lods: tuple[str, ...]
    score: int
    rating: str
    export_ready: bool
    import_readiness: ImportReadiness
    issues: tuple[ValidationIssue, ...] = ()
    messages: tuple[str, ...] = ()
