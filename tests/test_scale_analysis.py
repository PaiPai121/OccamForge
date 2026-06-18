from __future__ import annotations

from assetforge.analysis.scale_analysis import (
    ScaleAnalysisMesh,
    analyze_scale_persistence,
    scale_analysis_report_dict,
)


def _cube_mesh() -> ScaleAnalysisMesh:
    vertices = [
        (-1, -1, -1),
        (1, -1, -1),
        (1, 1, -1),
        (-1, 1, -1),
        (-1, -1, 1),
        (1, -1, 1),
        (1, 1, 1),
        (-1, 1, 1),
    ]
    triangles = [
        (0, 1, 2),
        (0, 2, 3),
        (4, 6, 5),
        (4, 7, 6),
        (0, 4, 5),
        (0, 5, 1),
        (1, 5, 6),
        (1, 6, 2),
        (2, 6, 7),
        (2, 7, 3),
        (3, 7, 4),
        (3, 4, 0),
    ]
    return ScaleAnalysisMesh(vertices=vertices, triangles=triangles, object_name="cube")


def _plate_with_small_spike() -> tuple[ScaleAnalysisMesh, list[int]]:
    vertices = [
        (-1.0, -1.0, 0.0),
        (0.0, -1.0, 0.0),
        (1.0, -1.0, 0.0),
        (-1.0, 0.0, 0.0),
        (-0.08, -0.08, 0.0),
        (0.08, -0.08, 0.0),
        (1.0, 0.0, 0.0),
        (-1.0, 1.0, 0.0),
        (-0.08, 0.08, 0.0),
        (0.08, 0.08, 0.0),
        (1.0, 1.0, 0.0),
        (0.0, 0.0, 0.18),
    ]
    triangles = [
        (0, 1, 3),
        (1, 4, 3),
        (1, 2, 5),
        (2, 6, 5),
        (3, 4, 7),
        (4, 8, 7),
        (5, 6, 10),
        (5, 10, 9),
        (7, 8, 10),
        (8, 9, 10),
        (4, 5, 11),
        (5, 9, 11),
        (9, 8, 11),
        (8, 4, 11),
    ]
    return ScaleAnalysisMesh(vertices=vertices, triangles=triangles, object_name="spike"), [4, 5, 8, 9, 11]


def test_scale_analysis_cube_does_not_crash() -> None:
    result = analyze_scale_persistence(_cube_mesh())

    assert result.errors == []
    assert result.vertex_count == 8
    assert result.triangle_count == 12
    assert len(result.scale_persistence) == 8
    assert len(result.tiny_detail_score) == 8


def test_cube_is_not_largely_tiny_detail() -> None:
    result = analyze_scale_persistence(_cube_mesh())

    tiny_ratio = sum(1 for score in result.tiny_detail_score if score >= 0.6) / len(result.tiny_detail_score)
    assert tiny_ratio <= 0.25


def test_small_spike_has_higher_tiny_detail_score() -> None:
    mesh, spike_indices = _plate_with_small_spike()
    result = analyze_scale_persistence(mesh, scales=[0.12, 0.24, 0.48, 0.96])

    spike_score = sum(result.tiny_detail_score[index] for index in spike_indices) / len(spike_indices)
    base_indices = [index for index in range(result.vertex_count) if index not in spike_indices]
    base_score = sum(result.tiny_detail_score[index] for index in base_indices) / len(base_indices)

    assert spike_score > base_score


def test_scale_analysis_report_fields_are_complete() -> None:
    result = analyze_scale_persistence(_cube_mesh())
    report = scale_analysis_report_dict(
        result,
        input_path="cube.obj",
        output_directory="scale_analysis",
        persistence_heatmap="scale_analysis/scale_persistence_heatmap.png",
        tiny_detail_heatmap="scale_analysis/tiny_detail_heatmap.png",
        mean_curvature_heatmap="scale_analysis/mean_curvature_heatmap.png",
        center_surround_heatmap="scale_analysis/center_surround_heatmap.png",
    )

    assert report["input"] == "cube.obj"
    assert report["object_name"] == "cube"
    assert report["vertex_count"] == 8
    assert report["triangle_count"] == 12
    assert "bbox_diagonal" in report
    assert "scales" in report
    assert "persistence_stats" in report
    assert "tiny_detail_stats" in report
    assert "mean_curvature_stats" in report
    assert "center_surround_stats" in report
    assert "interpretation" in report
    assert report["mean_curvature_heatmap"] == "scale_analysis/mean_curvature_heatmap.png"
    assert report["center_surround_heatmap"] == "scale_analysis/center_surround_heatmap.png"
