from __future__ import annotations

from pathlib import Path
from typing import Any

from assetforge.domain.geometry_report import (
    BoundingBox,
    BoundaryStats,
    CurvatureBucket,
    DenseRegion,
    GeometryOverallStats,
    GeometryReport,
    OptimizationCandidate,
    PlanarRegionStats,
    SilhouetteRegion,
    SilhouetteStats,
    SilhouetteTriangle,
    SilhouetteViewStats,
    TriangleDistribution,
)


def bounding_box_from_dict(payload: dict[str, Any]) -> BoundingBox:
    return BoundingBox(
        min_x=float(payload.get("min_x", 0.0)),
        min_y=float(payload.get("min_y", 0.0)),
        min_z=float(payload.get("min_z", 0.0)),
        max_x=float(payload.get("max_x", 0.0)),
        max_y=float(payload.get("max_y", 0.0)),
        max_z=float(payload.get("max_z", 0.0)),
    )


def bounding_box_to_dict(box: BoundingBox) -> dict[str, float]:
    return {
        "min_x": box.min_x,
        "min_y": box.min_y,
        "min_z": box.min_z,
        "max_x": box.max_x,
        "max_y": box.max_y,
        "max_z": box.max_z,
        "size_x": box.size_x,
        "size_y": box.size_y,
        "size_z": box.size_z,
    }


def geometry_report_from_dict(payload: dict[str, Any]) -> GeometryReport:
    overall_payload = payload.get("overall", {})
    silhouette_payload = payload.get("silhouette", {})
    return GeometryReport(
        source_file=Path(payload["source_file"]),
        report_json_path=Path(payload["report_json_path"]),
        heatmap_image_path=Path(payload["heatmap_image_path"]),
        overall=GeometryOverallStats(
            vertices=int(overall_payload.get("vertices", 0)),
            edges=int(overall_payload.get("edges", 0)),
            faces=int(overall_payload.get("faces", 0)),
            triangles=int(overall_payload.get("triangles", 0)),
            bounding_box=bounding_box_from_dict(overall_payload.get("bounding_box", {})),
        ),
        planar_regions=PlanarRegionStats(
            region_count=int(payload.get("planar_regions", {}).get("region_count", 0)),
            face_percentage=float(payload.get("planar_regions", {}).get("face_percentage", 0.0)),
            triangle_percentage=float(
                payload.get("planar_regions", {}).get("triangle_percentage", 0.0)
            ),
        ),
        curvature=tuple(
            CurvatureBucket(
                name=str(item.get("name", "")),
                triangle_count=int(item.get("triangle_count", 0)),
                percentage=float(item.get("percentage", 0.0)),
            )
            for item in payload.get("curvature", [])
        ),
        boundary=BoundaryStats(
            count=int(payload.get("boundary", {}).get("count", 0)),
            length=float(payload.get("boundary", {}).get("length", 0.0)),
        ),
        dense_regions=tuple(
            DenseRegion(
                region_id=str(item.get("region_id", "")),
                triangle_count=int(item.get("triangle_count", 0)),
                surface_area=float(item.get("surface_area", 0.0)),
                density=float(item.get("density", 0.0)),
            )
            for item in payload.get("dense_regions", [])
        ),
        silhouette=SilhouetteStats(
            view_count=int(silhouette_payload.get("view_count", 0)),
            total_outline_triangles=int(silhouette_payload.get("total_outline_triangles", 0)),
            protected_triangle_count=int(
                silhouette_payload.get("protected_triangle_count", 0)
            ),
            protected_triangle_percentage=float(
                silhouette_payload.get("protected_triangle_percentage", 0.0)
            ),
            max_hits=int(silhouette_payload.get("max_hits", 0)),
            views=tuple(
                SilhouetteViewStats(
                    name=str(item.get("name", "")),
                    outline_triangle_count=int(item.get("outline_triangle_count", 0)),
                )
                for item in silhouette_payload.get("views", [])
            ),
            top_triangles=tuple(
                SilhouetteTriangle(
                    object_name=str(item.get("object_name", "")),
                    triangle_index=int(item.get("triangle_index", 0)),
                    silhouette_hits=int(item.get("silhouette_hits", 0)),
                )
                for item in silhouette_payload.get("top_triangles", [])
            ),
            protected_regions=tuple(
                SilhouetteRegion(
                    region_id=str(item.get("region_id", "")),
                    object_name=str(item.get("object_name", "")),
                    triangle_count=int(item.get("triangle_count", 0)),
                    max_hits=int(item.get("max_hits", 0)),
                    average_hits=float(item.get("average_hits", 0.0)),
                    recommended_action=str(item.get("recommended_action", "")),
                )
                for item in silhouette_payload.get("protected_regions", [])
            ),
        ),
        triangle_distribution=TriangleDistribution(
            min_area=float(payload.get("triangle_distribution", {}).get("min_area", 0.0)),
            max_area=float(payload.get("triangle_distribution", {}).get("max_area", 0.0)),
            median_area=float(payload.get("triangle_distribution", {}).get("median_area", 0.0)),
        ),
        optimization_candidates=tuple(
            OptimizationCandidate(
                region_id=str(item.get("region_id", "")),
                region_type=str(item.get("region_type", "")),
                recommended_action=str(item.get("recommended_action", "")),
                triangle_count=int(item.get("triangle_count", 0)),
                surface_area=float(item.get("surface_area", 0.0)),
                density=float(item.get("density", 0.0)),
                curvature=float(item.get("curvature", 0.0)),
                silhouette_score=float(item.get("silhouette_score", 0.0)),
                confidence=float(item.get("confidence", 0.0)),
                rationale=str(item.get("rationale", "")),
            )
            for item in payload.get("optimization_candidates", [])
        ),
        warnings=tuple(str(item) for item in payload.get("warnings", [])),
        errors=tuple(str(item) for item in payload.get("errors", [])),
    )


def geometry_report_to_dict(report: GeometryReport) -> dict[str, Any]:
    return {
        "source_file": str(report.source_file),
        "report_json_path": str(report.report_json_path),
        "heatmap_image_path": str(report.heatmap_image_path),
        "overall": {
            "vertices": report.overall.vertices,
            "edges": report.overall.edges,
            "faces": report.overall.faces,
            "triangles": report.overall.triangles,
            "bounding_box": bounding_box_to_dict(report.overall.bounding_box),
        },
        "planar_regions": {
            "region_count": report.planar_regions.region_count,
            "face_percentage": report.planar_regions.face_percentage,
            "triangle_percentage": report.planar_regions.triangle_percentage,
        },
        "curvature": [
            {
                "name": item.name,
                "triangle_count": item.triangle_count,
                "percentage": item.percentage,
            }
            for item in report.curvature
        ],
        "boundary": {
            "count": report.boundary.count,
            "length": report.boundary.length,
        },
        "dense_regions": [
            {
                "region_id": item.region_id,
                "triangle_count": item.triangle_count,
                "surface_area": item.surface_area,
                "density": item.density,
            }
            for item in report.dense_regions
        ],
        "silhouette": {
            "view_count": report.silhouette.view_count,
            "total_outline_triangles": report.silhouette.total_outline_triangles,
            "protected_triangle_count": report.silhouette.protected_triangle_count,
            "protected_triangle_percentage": report.silhouette.protected_triangle_percentage,
            "max_hits": report.silhouette.max_hits,
            "views": [
                {
                    "name": item.name,
                    "outline_triangle_count": item.outline_triangle_count,
                }
                for item in report.silhouette.views
            ],
            "top_triangles": [
                {
                    "object_name": item.object_name,
                    "triangle_index": item.triangle_index,
                    "silhouette_hits": item.silhouette_hits,
                }
                for item in report.silhouette.top_triangles
            ],
            "protected_regions": [
                {
                    "region_id": item.region_id,
                    "object_name": item.object_name,
                    "triangle_count": item.triangle_count,
                    "max_hits": item.max_hits,
                    "average_hits": item.average_hits,
                    "recommended_action": item.recommended_action,
                }
                for item in report.silhouette.protected_regions
            ],
        },
        "triangle_distribution": {
            "min_area": report.triangle_distribution.min_area,
            "max_area": report.triangle_distribution.max_area,
            "median_area": report.triangle_distribution.median_area,
        },
        "optimization_candidates": [
            {
                "region_id": item.region_id,
                "region_type": item.region_type,
                "recommended_action": item.recommended_action,
                "triangle_count": item.triangle_count,
                "surface_area": item.surface_area,
                "density": item.density,
                "curvature": item.curvature,
                "silhouette_score": item.silhouette_score,
                "confidence": item.confidence,
                "rationale": item.rationale,
            }
            for item in report.optimization_candidates
        ],
        "warnings": list(report.warnings),
        "errors": list(report.errors),
    }
