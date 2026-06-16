from pathlib import Path

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
from assetforge.models.geometry_report_dto import geometry_report_from_dict, geometry_report_to_dict


def test_geometry_report_dto_round_trip() -> None:
    report = GeometryReport(
        source_file=Path("tank.blend"),
        report_json_path=Path("geometry_reports/geometry_report.json"),
        heatmap_image_path=Path("geometry_reports/geometry_report.png"),
        overall=GeometryOverallStats(
            vertices=10,
            edges=20,
            faces=8,
            triangles=12,
            bounding_box=BoundingBox(0, 1, 2, 3, 4, 5),
        ),
        planar_regions=PlanarRegionStats(
            region_count=3,
            face_percentage=92.5,
            triangle_percentage=91.0,
        ),
        curvature=(
            CurvatureBucket("Low Curvature", 7, 58.3),
            CurvatureBucket("Medium Curvature", 3, 25.0),
            CurvatureBucket("High Curvature", 2, 16.7),
        ),
        boundary=BoundaryStats(count=4, length=12.5),
        dense_regions=(DenseRegion("cell_1_2_3", 9, 0.25, 36.0),),
        silhouette=SilhouetteStats(
            view_count=6,
            total_outline_triangles=5,
            protected_triangle_count=3,
            protected_triangle_percentage=25.0,
            max_hits=4,
            views=(SilhouetteViewStats("Front", 2),),
            top_triangles=(SilhouetteTriangle("body", 7, 4),),
            protected_regions=(
                SilhouetteRegion("silhouette_body_1_2_3", "body", 3, 4, 2.5, "protect_candidate"),
            ),
        ),
        triangle_distribution=TriangleDistribution(
            min_area=0.01,
            max_area=1.25,
            median_area=0.16,
        ),
        optimization_candidates=(
            OptimizationCandidate(
                region_id="silhouette_body_1_2_3",
                region_type="silhouette_region",
                recommended_action="protect_candidate",
                triangle_count=3,
                surface_area=0.0,
                density=0.0,
                curvature=0.0,
                silhouette_score=4.0,
                confidence=0.9,
                rationale="outline",
            ),
        ),
        warnings=("warning",),
    )

    payload = geometry_report_to_dict(report)
    restored = geometry_report_from_dict(payload)

    assert restored.source_file == report.source_file
    assert restored.overall.triangles == 12
    assert restored.overall.bounding_box.size_x == 3
    assert restored.planar_regions.region_count == 3
    assert restored.curvature[2].name == "High Curvature"
    assert restored.dense_regions[0].density == 36.0
    assert restored.silhouette.max_hits == 4
    assert restored.silhouette.protected_regions[0].recommended_action == "protect_candidate"
    assert restored.optimization_candidates[0].recommended_action == "protect_candidate"
    assert restored.warnings == ("warning",)
