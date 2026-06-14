from assetforge.services.optimization_preview import OptimizationPreviewService


def test_preview_generates_comparison_options() -> None:
    report = OptimizationPreviewService().preview(
        original_triangle_count=62656,
        profile_id="cities_skylines_vehicle",
        targets=(5000, 10000, 15000, 25000),
    )

    assert report.original_triangle_count == 62656
    assert [option.target_triangle_count for option in report.options] == [
        5000,
        10000,
        15000,
        25000,
    ]
    assert report.options[0].estimated_triangle_count == 5000
    assert report.options[0].estimated_compatibility_score == 85
    assert report.options[-1].rating == "Critical"


def test_preview_caps_estimated_triangles_at_original_count() -> None:
    report = OptimizationPreviewService().preview(
        original_triangle_count=4000,
        targets=(5000,),
    )

    assert report.options[0].estimated_triangle_count == 4000
    assert report.options[0].reduction_percentage == 0.0
