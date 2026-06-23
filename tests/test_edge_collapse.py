from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

from assetforge.analysis.edge_collapse import (
    CollapseExecutor,
    ComboCostProvider,
    Edge,
    EdgeCollapseMesh,
    HybridCostProvider,
    MidpointPlacement,
    QEMCostProvider,
    QEMPlacement,
    StaticEdgeScoreProvider,
    StaticPriorProvider,
    _CollapseState,
    _optimal_qem_position,
)


def _strip_mesh() -> EdgeCollapseMesh:
    return EdgeCollapseMesh(
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (2.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
            (2.0, 1.0, 0.0),
        ],
        triangles=[
            (0, 1, 4),
            (0, 4, 3),
            (1, 2, 5),
            (1, 5, 4),
        ],
        object_name="strip",
    )


def _two_component_mesh() -> EdgeCollapseMesh:
    return EdgeCollapseMesh(
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
            (10.0, 0.0, 0.0),
            (11.0, 0.0, 0.0),
            (10.0, 1.0, 0.0),
            (11.0, 1.0, 0.0),
        ],
        triangles=[
            (0, 1, 3),
            (0, 3, 2),
            (4, 5, 7),
            (4, 7, 6),
        ],
        object_name="two_components",
    )


def _cube_mesh() -> EdgeCollapseMesh:
    return EdgeCollapseMesh(
        vertices=[
            (-1.0, -1.0, -1.0),
            (1.0, -1.0, -1.0),
            (1.0, 1.0, -1.0),
            (-1.0, 1.0, -1.0),
            (-1.0, -1.0, 1.0),
            (1.0, -1.0, 1.0),
            (1.0, 1.0, 1.0),
            (-1.0, 1.0, 1.0),
        ],
        triangles=[
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
        ],
        object_name="cube",
    )


def _grid_mesh(width: int = 3, height: int = 3) -> EdgeCollapseMesh:
    vertices = [
        (float(x), float(y), 0.0)
        for y in range(height + 1)
        for x in range(width + 1)
    ]
    triangles: list[tuple[int, int, int]] = []
    stride = width + 1
    for y in range(height):
        for x in range(width):
            a = y * stride + x
            b = a + 1
            c = a + stride
            d = c + 1
            triangles.extend([(a, b, d), (a, d, c)])
    return EdgeCollapseMesh(vertices=vertices, triangles=triangles, object_name="grid")


def _simple_cylinder(segments: int = 8) -> EdgeCollapseMesh:
    vertices = [(0.0, 0.0, -1.0), (0.0, 0.0, 1.0)]
    for z in (-1.0, 1.0):
        for index in range(segments):
            angle = index / segments * math.tau
            vertices.append((round(math.cos(angle), 8), round(math.sin(angle), 8), z))
    bottom = 2
    top = 2 + segments
    triangles: list[tuple[int, int, int]] = []
    for index in range(segments):
        next_index = (index + 1) % segments
        b0 = bottom + index
        b1 = bottom + next_index
        t0 = top + index
        t1 = top + next_index
        triangles.extend([(0, b1, b0), (1, t0, t1), (b0, b1, t1), (b0, t1, t0)])
    return EdgeCollapseMesh(vertices=vertices, triangles=triangles, object_name="cylinder")


class CountingStaticCostProvider:
    name = "CountingStaticCostProvider"

    def __init__(self, scores: dict[Edge, float]) -> None:
        self.scores = scores
        self.calls: Counter[Edge] = Counter()

    def score(self, edge: Edge, mesh_state: object) -> float:
        self.calls[edge] += 1
        return self.scores.get(edge, 100.0)


def test_executor_uses_injected_static_score_for_first_collapse() -> None:
    scorer = StaticEdgeScoreProvider({(0, 1): 0.99, (1, 4): 0.10})

    result = CollapseExecutor(scorer, MidpointPlacement()).simplify(
        _strip_mesh(),
        target_triangle_count=3,
    )

    assert result.collapsed_edge_count == 1
    assert result.steps[0].edge == (0, 1)
    assert result.steps[0].cost == 0.0
    assert result.steps[0].placement == (0.5, 0.0, 0.0)
    assert result.report_dict()["cost_provider_name"] == "StaticEdgeScoreProvider"
    assert result.report_dict()["placement_provider_name"] == "MidpointPlacement"


def test_executor_updates_local_topology_and_recomputes_local_scores() -> None:
    scorer = CountingStaticCostProvider({(0, 1): 0.01, (0, 2): 0.02})

    result = CollapseExecutor(scorer, MidpointPlacement()).simplify(
        _strip_mesh(),
        target_triangle_count=2,
    )

    assert [step.edge for step in result.steps] == [(0, 1), (0, 2)]
    assert result.original_triangle_count == 4
    assert len(result.triangles) == 2
    assert scorer.calls[(0, 4)] >= 2


def test_executor_does_not_recompute_disconnected_component_edges() -> None:
    scorer = CountingStaticCostProvider({(0, 1): 0.01})

    result = CollapseExecutor(scorer, MidpointPlacement()).simplify(
        _two_component_mesh(),
        target_triangle_count=3,
    )

    assert result.steps[0].edge == (0, 1)
    assert scorer.calls[(4, 5)] == 1
    assert scorer.calls[(5, 7)] == 1


def test_two_ring_conflict_scope_separates_disconnected_edges() -> None:
    state = _CollapseState(_two_component_mesh())

    first_vertices, first_faces = state.conflict_scope((0, 1), ring_depth=2)
    second_vertices, second_faces = state.conflict_scope((4, 5), ring_depth=2)

    assert first_vertices.isdisjoint(second_vertices)
    assert first_faces.isdisjoint(second_faces)


def test_two_ring_conflict_scope_rejects_nearby_edges() -> None:
    state = _CollapseState(_strip_mesh())

    first_vertices, first_faces = state.conflict_scope((0, 1), ring_depth=2)
    second_vertices, second_faces = state.conflict_scope((1, 2), ring_depth=2)

    assert first_vertices & second_vertices
    assert first_faces & second_faces


def test_executor_batches_two_ring_independent_edges() -> None:
    scorer = StaticEdgeScoreProvider(
        {
            (0, 1): 1.0,
            (4, 5): 0.95,
            (0, 3): 0.10,
            (4, 7): 0.10,
        }
    )

    result = CollapseExecutor(scorer, MidpointPlacement()).simplify(
        _two_component_mesh(),
        target_triangle_count=2,
        batch_size=2,
        batch_ring_depth=2,
    )

    assert result.collapsed_edge_count == 2
    assert {step.edge for step in result.steps} == {(0, 1), (4, 5)}
    assert len(result.triangles) == 2


def test_executor_stops_at_target_triangle_count() -> None:
    scorer = StaticEdgeScoreProvider(
        {edge: index for index, edge in enumerate([(0, 1), (0, 2), (3, 4)])}
    )

    result = CollapseExecutor(scorer, MidpointPlacement()).simplify(
        _strip_mesh(),
        target_triangle_count=3,
    )

    assert result.collapsed_edge_count == 1
    assert len(result.triangles) == 3


def test_combo_cost_provider_can_drive_current_afcost_experiment_input() -> None:
    combo_scores = {(0, 1): 0.95, (1, 4): 0.10, (0, 4): 0.20}

    result = CollapseExecutor(HybridCostProvider(combo_scores), MidpointPlacement()).simplify(
        _strip_mesh(),
        target_triangle_count=3,
    )

    assert result.steps[0].edge == (0, 1)
    assert result.report_dict()["cost_provider_name"] == "HybridCostProvider"


def test_combo_cost_provider_aliases_hybrid_provider_for_existing_callers() -> None:
    assert ComboCostProvider is HybridCostProvider


def test_static_prior_inherits_through_collapsed_vertex_lineage() -> None:
    state = _CollapseState(_strip_mesh())
    prior = StaticPriorProvider({(0, 1): 0.95, (1, 2): 0.70})

    step = state.collapse((0, 1), cost=0.0, placement=(0.5, 0.0, 0.0))

    assert step is not None
    assert (0, 2) in state.edge_faces
    assert prior.prior((0, 2), state) == 0.95


def test_static_provider_can_keep_low_cost_semantics_for_custom_costs() -> None:
    costs = {(0, 1): 0.01, (1, 4): 0.20, (0, 4): 0.10}

    result = CollapseExecutor(
        StaticEdgeScoreProvider(costs, higher_scores_first=False),
        MidpointPlacement(),
    ).simplify(
        _strip_mesh(),
        target_triangle_count=3,
    )

    assert result.steps[0].edge == (0, 1)


def test_qem_cost_and_placement_simplify_cube_without_being_the_only_ranking_path() -> None:
    result = CollapseExecutor(QEMCostProvider(), QEMPlacement()).simplify(
        _cube_mesh(),
        target_triangle_count=10,
    )

    assert result.original_triangle_count == 12
    assert len(result.triangles) <= 10
    assert result.collapsed_edge_count >= 1
    assert result.report_dict()["cost_provider_name"] == "QEMCostProvider"


def test_synthetic_grid_simplifies_with_static_scores() -> None:
    result = CollapseExecutor(StaticEdgeScoreProvider({}, default_score=1.0), MidpointPlacement()).simplify(
        _grid_mesh(),
        target_triangle_count=12,
    )

    assert result.original_triangle_count == 18
    assert len(result.triangles) <= 12
    assert result.report_dict()["collapse_count"] == result.collapsed_edge_count


def test_simple_cylinder_simplifies_with_qem_cost_and_midpoint_placement() -> None:
    result = CollapseExecutor(QEMCostProvider(), MidpointPlacement()).simplify(
        _simple_cylinder(),
        target_triangle_count=24,
    )

    assert result.original_triangle_count == 32
    assert len(result.triangles) <= 24
    assert "runtime" in result.report_dict()


def test_result_writes_required_report_json_fields(tmp_path: Path) -> None:
    result = CollapseExecutor(StaticEdgeScoreProvider({(0, 1): 0.01}), MidpointPlacement()).simplify(
        _strip_mesh(),
        target_triangle_count=3,
    )
    report_path = tmp_path / "report.json"

    result.write_report_json(report_path)

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report == result.report_dict()
    assert set(report) == {
        "input_triangles",
        "output_triangles",
        "collapse_count",
        "skipped_invalid_edges",
        "runtime",
        "cost_provider_name",
        "placement_provider_name",
    }


class FarPlacement:
    name = "FarPlacement"

    def place(self, edge: Edge, mesh_state: object) -> tuple[float, float, float]:
        return (1000.0, 1000.0, 1000.0)


def test_executor_rejects_far_placement() -> None:
    result = CollapseExecutor(StaticEdgeScoreProvider({(0, 1): 0.01}), FarPlacement()).simplify(
        _strip_mesh(),
        target_triangle_count=3,
    )

    assert result.collapsed_edge_count == 0
    assert result.skipped_invalid_edges >= 1


def test_qem_placement_is_constrained_to_current_edge_segment() -> None:
    quadric = [
        [1.0, 0.0, 0.0, -100.0],
        [0.0, 1.0, 0.0, -100.0],
        [0.0, 0.0, 1.0, -100.0],
        [-100.0, -100.0, -100.0, 30000.0],
    ]

    placement = _optimal_qem_position(quadric, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0))

    assert placement == (1.0, 0.0, 0.0)


def test_validation_rejects_boundary_to_interior_collapse() -> None:
    mesh = EdgeCollapseMesh(
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (1.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.5, 0.5, 0.0),
        ],
        triangles=[
            (0, 1, 4),
            (1, 2, 4),
            (2, 3, 4),
            (3, 0, 4),
        ],
    )
    state = _CollapseState(mesh)

    assert not state.can_collapse((0, 4), (0.25, 0.25, 0.0))


def test_validation_rejects_local_normal_flip() -> None:
    mesh = EdgeCollapseMesh(
        vertices=[
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            (1.0, 1.0, 0.0),
        ],
        triangles=[
            (0, 1, 2),
            (1, 3, 2),
        ],
    )
    state = _CollapseState(mesh)

    assert not state.can_collapse((0, 1), (0.5, 2.0, 0.0))
