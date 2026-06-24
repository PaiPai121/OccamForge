from __future__ import annotations

import heapq
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence


Vector3 = tuple[float, float, float]
Triangle = tuple[int, int, int]
Edge = tuple[int, int]
MAX_PLACEMENT_EDGE_LENGTH_MULTIPLIER = 2.0
MAX_NEW_EDGE_LENGTH_MULTIPLIER = 4.0
MIN_NORMAL_DOT = 0.05
DEFAULT_BATCH_SIZE = 8
DEFAULT_BATCH_RING_DEPTH = 2
MAX_BATCH_SCAN_MULTIPLIER = 4


@dataclass(frozen=True, slots=True)
class EdgeCollapseMesh:
    vertices: Sequence[Vector3]
    triangles: Sequence[Triangle]
    object_name: str = "mesh"


@dataclass(frozen=True, slots=True)
class EdgeCostContext:
    edge: Edge
    vertices: Sequence[Vector3]
    triangles: Sequence[Triangle]
    edge_face_count: int
    is_boundary: bool


class MeshState(Protocol):
    vertices: Sequence[Vector3]

    @property
    def triangles_sequence(self) -> Sequence[Triangle]:
        raise NotImplementedError

    def cost_context(self, edge: Edge) -> EdgeCostContext:
        raise NotImplementedError

    def vertex_quadrics(self) -> list[list[list[float]]]:
        raise NotImplementedError

    def vertex_sources(self, vertex: int) -> frozenset[int]:
        raise NotImplementedError

    def vertex_source_version(self, vertex: int) -> int:
        raise NotImplementedError

    def qem_edge_evaluation(self, edge: Edge) -> tuple[Vector3, float]:
        raise NotImplementedError

    def topology_version(self) -> int:
        raise NotImplementedError

    def vertex_neighbors(self, vertex: int, ring_depth: int = 1) -> set[int]:
        raise NotImplementedError

    def incident_faces(self, vertex: int) -> Sequence[Triangle]:
        raise NotImplementedError


class CostProvider(Protocol):
    """Pluggable edge ranking contract for QEM, AFCost_xx, persistence, or hybrids."""

    name: str

    def score(self, edge: Edge, mesh_state: MeshState) -> float:
        raise NotImplementedError


class PlacementProvider(Protocol):
    """Pluggable edge placement contract, independent from edge ranking."""

    name: str

    def place(self, edge: Edge, mesh_state: MeshState) -> Vector3:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class EdgeCollapseStep:
    edge: Edge
    kept_vertex: int
    removed_vertex: int
    cost: float
    placement: Vector3
    removed_triangle_count: int
    triangle_count: int


@dataclass(frozen=True, slots=True)
class EdgeCollapseResult:
    vertices: list[Vector3]
    triangles: list[Triangle]
    steps: list[EdgeCollapseStep]
    original_vertex_count: int
    original_triangle_count: int
    target_triangle_count: int
    skipped_invalid_edges: int
    runtime_seconds: float
    cost_provider_name: str
    placement_provider_name: str

    @property
    def collapsed_edge_count(self) -> int:
        return len(self.steps)

    def report_dict(self) -> dict[str, object]:
        return {
            "input_triangles": self.original_triangle_count,
            "output_triangles": len(self.triangles),
            "collapse_count": self.collapsed_edge_count,
            "skipped_invalid_edges": self.skipped_invalid_edges,
            "runtime": self.runtime_seconds,
            "cost_provider_name": self.cost_provider_name,
            "placement_provider_name": self.placement_provider_name,
        }

    def write_report_json(self, output_path: Path) -> None:
        output_path.write_text(json.dumps(self.report_dict(), indent=2), encoding="utf-8")


class StaticEdgeScoreProvider:
    name = "StaticEdgeScoreProvider"

    def __init__(
        self,
        scores: dict[Edge, float],
        default_score: float | None = None,
        *,
        higher_scores_first: bool = True,
    ) -> None:
        self._scores = {_edge(*edge): float(score) for edge, score in scores.items()}
        self._default_score = None if default_score is None else float(default_score)
        self._higher_scores_first = higher_scores_first
        finite_scores = [score for score in self._scores.values() if math.isfinite(score)]
        if self._default_score is not None and math.isfinite(self._default_score):
            finite_scores.append(self._default_score)
        self._max_score = max(finite_scores, default=0.0)

    def score(self, edge: Edge, mesh_state: MeshState) -> float:
        raw_score = self._scores.get(edge, self._default_score)
        if raw_score is None or not math.isfinite(raw_score):
            return math.inf
        if not self._higher_scores_first:
            return raw_score
        # Heatmap/AFCost scores are deletion priorities; the executor heap consumes costs.
        return max(0.0, self._max_score - raw_score)


class StaticPriorProvider:
    """Maps static deletion-priority scores onto current mesh edges.

    Original AFCost/heatmap scores are edge based. After collapses create new edges,
    the prior is inherited through vertex lineages instead of dropping to QEM only.
    """

    name = "StaticPriorProvider"

    def __init__(self, edge_priors: dict[Edge, float], default_prior: float = 0.0) -> None:
        self._edge_priors = {_edge(*edge): float(prior) for edge, prior in edge_priors.items()}
        self._default_prior = float(default_prior)
        self._vertex_priors: dict[int, float] = defaultdict(lambda: self._default_prior)
        for edge, prior in self._edge_priors.items():
            if not math.isfinite(prior):
                continue
            self._vertex_priors[edge[0]] = max(self._vertex_priors[edge[0]], prior)
            self._vertex_priors[edge[1]] = max(self._vertex_priors[edge[1]], prior)
        candidates = [prior for prior in self._edge_priors.values() if math.isfinite(prior)]
        candidates.extend(prior for prior in self._vertex_priors.values() if math.isfinite(prior))
        self._max_prior = max(candidates, default=max(0.0, self._default_prior))
        self._vertex_prior_cache: dict[tuple[int, int, int], float] = {}

    @property
    def max_prior(self) -> float:
        return self._max_prior

    def prior(self, edge: Edge, mesh_state: MeshState) -> float:
        direct = self._edge_priors.get(edge)
        if direct is not None and math.isfinite(direct):
            return direct
        return max(self._vertex_prior(vertex, mesh_state) for vertex in edge)

    def normalized_prior(self, edge: Edge, mesh_state: MeshState) -> float:
        scale = max(abs(self.max_prior), 1e-12)
        return max(0.0, self.prior(edge, mesh_state)) / scale

    def _vertex_prior(self, vertex: int, mesh_state: MeshState) -> float:
        key = (id(mesh_state), vertex, mesh_state.vertex_source_version(vertex))
        cached = self._vertex_prior_cache.get(key)
        if cached is not None:
            return cached
        best = self._default_prior
        for source_vertex in mesh_state.vertex_sources(vertex):
            prior = self._vertex_priors.get(source_vertex, self._default_prior)
            if math.isfinite(prior):
                best = max(best, prior)
        self._vertex_prior_cache[key] = best
        return best


class HybridCostProvider:
    """Dynamic edge cost: current QEM geometry risk minus static deletion prior."""

    name = "HybridCostProvider"

    def __init__(
        self,
        static_priors: dict[Edge, float],
        default_prior: float = 0.0,
        *,
        dynamic_weight: float = 1.0,
        prior_weight: float = 1.0,
    ) -> None:
        self._static_prior = StaticPriorProvider(static_priors, default_prior)
        self._qem = QEMCostProvider()
        self._dynamic_weight = float(dynamic_weight)
        self._prior_weight = float(prior_weight)
        self._scale_cache: dict[int, float] = {}

    def score(self, edge: Edge, mesh_state: MeshState) -> float:
        dynamic_geometry_cost = self._dynamic_geometry_cost(edge, mesh_state)
        if not math.isfinite(dynamic_geometry_cost):
            return math.inf
        static_prior = self._static_prior.normalized_prior(edge, mesh_state)
        return self._dynamic_weight * dynamic_geometry_cost - self._prior_weight * static_prior

    def _dynamic_geometry_cost(self, edge: Edge, mesh_state: MeshState) -> float:
        qem_cost = self._qem.score(edge, mesh_state)
        if not math.isfinite(qem_cost):
            return math.inf
        scale = self._scale_cache.get(id(mesh_state))
        if scale is None:
            scale = _mesh_diagonal_squared(mesh_state.vertices)
            self._scale_cache[id(mesh_state)] = scale
        return math.log1p(max(0.0, qem_cost) / max(scale, 1e-12))


ComboCostProvider = HybridCostProvider


@dataclass(frozen=True, slots=True)
class _AFCostSignals:
    qem_log: float
    persistence: float
    tiny_detail: float
    qem_cost: float


@dataclass(frozen=True, slots=True)
class _RangeNormalizer:
    low: float
    high: float

    @classmethod
    def from_values(cls, values: Sequence[float]) -> "_RangeNormalizer":
        finite = [float(value) for value in values if math.isfinite(float(value))]
        if not finite:
            return cls(0.0, 1.0)
        low = min(finite)
        high = max(finite)
        if high - low <= 1e-12:
            high = low + 1.0
        return cls(low, high)

    def normalize(self, value: float) -> float:
        if not math.isfinite(value):
            return 0.0
        return max(0.0, min(1.0, (float(value) - self.low) / (self.high - self.low)))


class _AFCostDynamicNormalizer:
    def __init__(self, signals: Sequence[_AFCostSignals], eps: float) -> None:
        self._eps = float(eps)
        self._qem_base = _RangeNormalizer.from_values([signal.qem_log for signal in signals])
        self._p = _RangeNormalizer.from_values([signal.persistence for signal in signals])
        self._d = _RangeNormalizer.from_values([signal.tiny_detail for signal in signals])
        projected = [self.project(signal) for signal in signals]
        p_values = [item[1] for item in projected]
        d_values = [item[2] for item in projected]
        self._p_over_d = _RangeNormalizer.from_values(
            [p / (d + self._eps) for p, d in zip(p_values, d_values, strict=False)]
        )
        self._d_over_p = _RangeNormalizer.from_values(
            [d / (p + self._eps) for p, d in zip(p_values, d_values, strict=False)]
        )
        self._p_minus_d = _RangeNormalizer.from_values(
            [p - d for p, d in zip(p_values, d_values, strict=False)]
        )
        self._d_minus_p = _RangeNormalizer.from_values(
            [d - p for p, d in zip(p_values, d_values, strict=False)]
        )
        self._p_inv_d = _RangeNormalizer.from_values(
            [p * (1.0 - d) for p, d in zip(p_values, d_values, strict=False)]
        )

    def project(self, signal: _AFCostSignals) -> tuple[float, float, float]:
        return (
            self._qem_base.normalize(signal.qem_log),
            self._p.normalize(signal.persistence),
            self._d.normalize(signal.tiny_detail),
        )

    def combination_factor(self, name: str, p: float, d: float) -> float:
        if name == "AFCost_07":
            return self._p_over_d.normalize(p / (d + self._eps))
        if name == "AFCost_08":
            return self._d_over_p.normalize(d / (p + self._eps))
        if name == "AFCost_09":
            return self._p_minus_d.normalize(p - d)
        if name == "AFCost_10":
            return self._d_minus_p.normalize(d - p)
        if name == "AFCost_11":
            return self._p_inv_d.normalize(p * (1.0 - d))
        raise ValueError(f"Unsupported normalized AFCost factor: {name}")


class SelectedAFCostProvider:
    """Dynamically recompute one selected AFCost candidate on locally changed edges.

    The candidate formula is fixed by the user selection. Normalization ranges are
    frozen from the initial mesh, so local recompute does not rescale each small
    neighborhood independently.
    """

    name = "SelectedAFCostProvider"
    _SUPPORTED = {f"AFCost_{index:02d}" for index in range(12)}

    def __init__(
        self,
        candidate_name: str,
        normalizer: _AFCostDynamicNormalizer,
        *,
        lambda_value: float = 1.0,
        eps: float = 1e-6,
        geometry_safety_weight: float = 0.25,
    ) -> None:
        if candidate_name not in self._SUPPORTED:
            raise ValueError(f"Unsupported AFCost candidate: {candidate_name}")
        self._candidate_name = candidate_name
        self._normalizer = normalizer
        self._lambda = float(lambda_value)
        self._eps = float(eps)
        self._geometry_safety_weight = float(geometry_safety_weight)
        self._mesh_scale_cache: dict[int, float] = {}
        self._vertex_signal_cache: dict[tuple[int, int, int], tuple[float, float]] = {}

    @classmethod
    def from_mesh(
        cls,
        mesh: EdgeCollapseMesh,
        candidate_name: str,
        *,
        lambda_value: float = 1.0,
        eps: float = 1e-6,
        geometry_safety_weight: float = 0.25,
    ) -> "SelectedAFCostProvider":
        state = _CollapseState(mesh)
        signals = [
            _edge_afcost_signals(edge, state, float(eps), {})
            for edge in sorted(state.edge_faces)
        ]
        return cls(
            candidate_name,
            _AFCostDynamicNormalizer(signals, float(eps)),
            lambda_value=lambda_value,
            eps=eps,
            geometry_safety_weight=geometry_safety_weight,
        )

    @property
    def candidate_name(self) -> str:
        return self._candidate_name

    def score(self, edge: Edge, mesh_state: MeshState) -> float:
        signal = _edge_afcost_signals(edge, mesh_state, self._eps, self._vertex_signal_cache)
        qem_base, p_value, d_value = self._normalizer.project(signal)
        candidate_score = self._candidate_score(qem_base, p_value, d_value)
        scale = self._mesh_scale_cache.get(id(mesh_state))
        if scale is None:
            scale = _mesh_diagonal_squared(mesh_state.vertices)
            self._mesh_scale_cache[id(mesh_state)] = scale
        geometry_safety = math.log1p(max(0.0, signal.qem_cost) / max(scale, 1e-12))
        return self._geometry_safety_weight * geometry_safety - candidate_score

    def _candidate_score(self, qem_base: float, p_value: float, d_value: float) -> float:
        inv_p = 1.0 - p_value
        inv_d = 1.0 - d_value
        name = self._candidate_name
        if name == "AFCost_00":
            return qem_base
        if name == "AFCost_01":
            return qem_base * (1.0 + self._lambda * p_value)
        if name == "AFCost_02":
            return qem_base * (1.0 + self._lambda * inv_d)
        if name == "AFCost_03":
            return qem_base * (1.0 + self._lambda * p_value * inv_d)
        if name == "AFCost_04":
            return qem_base * max(0.0, 1.0 - self._lambda * d_value)
        if name == "AFCost_05":
            return qem_base * max(0.0, 1.0 - self._lambda * inv_p)
        if name == "AFCost_06":
            return qem_base * max(0.0, 1.0 - self._lambda * d_value * inv_p)
        if name in {"AFCost_07", "AFCost_08", "AFCost_09", "AFCost_10", "AFCost_11"}:
            return qem_base * self._normalizer.combination_factor(name, p_value, d_value)
        return math.inf


class QEMCostProvider:
    name = "QEMCostProvider"

    def score(self, edge: Edge, mesh_state: MeshState) -> float:
        _, cost = mesh_state.qem_edge_evaluation(edge)
        return cost


class MidpointPlacement:
    name = "MidpointPlacement"

    def place(self, edge: Edge, mesh_state: MeshState) -> Vector3:
        return _midpoint(mesh_state.vertices[edge[0]], mesh_state.vertices[edge[1]])


class QEMPlacement:
    name = "QEMPlacement"

    def place(self, edge: Edge, mesh_state: MeshState) -> Vector3:
        placement, _ = mesh_state.qem_edge_evaluation(edge)
        return placement


class CollapseExecutor:
    """Priority-queue edge-collapse executor with injectable edge costs.

    The executor owns topology mutation only. It never embeds a scoring formula:
    every edge priority and placement comes from supplied provider interfaces.
    """

    def __init__(self, cost_provider: CostProvider, placement_provider: PlacementProvider) -> None:
        self._cost_provider = cost_provider
        self._placement_provider = placement_provider

    def simplify(
        self,
        mesh: EdgeCollapseMesh,
        target_triangle_count: int,
        max_collapses: int | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        batch_ring_depth: int = DEFAULT_BATCH_RING_DEPTH,
        progress_callback: Callable[[dict[str, int]], None] | None = None,
    ) -> EdgeCollapseResult:
        if target_triangle_count < 0:
            raise ValueError("target_triangle_count must be non-negative")
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if batch_ring_depth < 0:
            raise ValueError("batch_ring_depth must be non-negative")

        started_at = time.perf_counter()
        state = _CollapseState(mesh)
        estimated_total_collapses = max(
            1,
            math.ceil(max(0, state.triangle_count - target_triangle_count) / 2),
        )
        if max_collapses is not None:
            estimated_total_collapses = min(estimated_total_collapses, max_collapses)
        heap: list[tuple[float, int, Edge, int]] = []
        sequence = 0
        skipped_invalid_edges = 0

        def push(edge: Edge) -> None:
            nonlocal sequence
            if edge not in state.edge_faces:
                return
            version = state.bump_edge_version(edge)
            cost = self._cost_provider.score(edge, state)
            if not math.isfinite(cost):
                return
            heapq.heappush(heap, (float(cost), sequence, edge, version))
            sequence += 1

        for edge in sorted(state.edge_faces):
            push(edge)

        steps: list[EdgeCollapseStep] = []
        while state.triangle_count > target_triangle_count and heap:
            if max_collapses is not None and len(steps) >= max_collapses:
                break
            remaining_collapses = None if max_collapses is None else max_collapses - len(steps)
            target_gap = max(1, state.triangle_count - target_triangle_count)
            current_batch_size = min(batch_size, target_gap)
            if remaining_collapses is not None:
                current_batch_size = min(current_batch_size, remaining_collapses)

            batch: list[tuple[float, Edge, int, Vector3]] = []
            held_entries: list[tuple[float, int, Edge, int]] = []
            batch_vertices: set[int] = set()
            batch_faces: set[int] = set()
            scanned = 0
            max_scan = max(current_batch_size * MAX_BATCH_SCAN_MULTIPLIER, current_batch_size)

            while heap and len(batch) < current_batch_size and scanned < max_scan:
                scanned += 1
                cost_value, entry_sequence, edge, version = heapq.heappop(heap)
                if not state.is_current_edge(edge, version):
                    skipped_invalid_edges += 1
                    continue

                placement = self._placement_provider.place(edge, state)
                if not _is_finite_vector(placement):
                    skipped_invalid_edges += 1
                    continue
                if not state.can_collapse(edge, placement):
                    skipped_invalid_edges += 1
                    continue

                scope_vertices, scope_faces = state.conflict_scope(edge, batch_ring_depth)
                if scope_vertices & batch_vertices or scope_faces & batch_faces:
                    held_entries.append((cost_value, entry_sequence, edge, version))
                    continue

                batch.append((float(cost_value), edge, version, placement))
                batch_vertices.update(scope_vertices)
                batch_faces.update(scope_faces)

            for entry in held_entries:
                heapq.heappush(heap, entry)

            if not batch:
                continue

            affected_vertices: set[int] = set()
            for cost_value, edge, version, placement in batch:
                if state.triangle_count <= target_triangle_count:
                    break
                if not state.is_current_edge(edge, version):
                    skipped_invalid_edges += 1
                    continue
                if not state.can_collapse(edge, placement):
                    skipped_invalid_edges += 1
                    continue
                affected_vertices.update(state.affected_vertices(edge))
                step = state.collapse(edge, cost_value, placement)
                if step is None:
                    skipped_invalid_edges += 1
                    continue
                steps.append(step)
                affected_vertices.add(step.kept_vertex)

            for next_edge in sorted(state.edges_touching_any(affected_vertices)):
                push(next_edge)
            if progress_callback is not None and steps:
                progress_callback(
                    {
                        "collapse_count": len(steps),
                        "estimated_total_collapses": estimated_total_collapses,
                        "current_triangles": state.triangle_count,
                        "target_triangles": target_triangle_count,
                    }
                )

        return EdgeCollapseResult(
            vertices=state.compact_vertices(),
            triangles=state.compact_triangles(),
            steps=steps,
            original_vertex_count=len(mesh.vertices),
            original_triangle_count=len(mesh.triangles),
            target_triangle_count=target_triangle_count,
            skipped_invalid_edges=skipped_invalid_edges,
            runtime_seconds=time.perf_counter() - started_at,
            cost_provider_name=self._cost_provider.name,
            placement_provider_name=self._placement_provider.name,
        )


LocalEdgeCollapseExecutor = CollapseExecutor


class _CollapseState:
    def __init__(self, mesh: EdgeCollapseMesh) -> None:
        self.vertices = [tuple(map(float, vertex)) for vertex in mesh.vertices]
        self.alive_vertices = set(range(len(self.vertices)))
        self.vertex_lineage: list[set[int]] = [{index} for index in range(len(self.vertices))]
        self.vertex_lineage_versions = [0 for _ in self.vertices]
        self._topology_version = 0
        self.triangles: dict[int, Triangle] = {}
        for index, triangle in enumerate(mesh.triangles):
            valid = _valid_triangle(triangle, len(self.vertices))
            if valid is not None:
                self.triangles[index] = valid
        self.edge_faces: dict[Edge, set[int]] = {}
        self.vertex_edges: dict[int, set[Edge]] = {}
        self.vertex_faces: dict[int, set[int]] = {}
        self.edge_versions: dict[Edge, int] = defaultdict(int)
        self.qem_edge_cache: dict[tuple[Edge, int], tuple[Vector3, float]] = {}
        self.conflict_scope_cache: dict[tuple[Edge, int, int], tuple[set[int], set[int]]] = {}
        self._vertex_quadrics: list[list[list[float]]] | None = None
        self._build_initial_topology()

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)

    @property
    def triangles_sequence(self) -> Sequence[Triangle]:
        return list(self.triangles.values())

    def cost_context(self, edge: Edge) -> EdgeCostContext:
        face_ids = self.edge_faces.get(edge, set())
        return EdgeCostContext(
            edge=edge,
            vertices=self.vertices,
            triangles=list(self.triangles.values()),
            edge_face_count=len(face_ids),
            is_boundary=len(face_ids) == 1,
        )

    def vertex_quadrics(self) -> list[list[list[float]]]:
        if self._vertex_quadrics is None:
            self._vertex_quadrics = _vertex_quadrics(self.vertices, self.triangles_sequence)
        return self._vertex_quadrics

    def vertex_sources(self, vertex: int) -> frozenset[int]:
        if vertex < 0 or vertex >= len(self.vertex_lineage):
            return frozenset()
        return frozenset(self.vertex_lineage[vertex])

    def vertex_source_version(self, vertex: int) -> int:
        if vertex < 0 or vertex >= len(self.vertex_lineage_versions):
            return -1
        return self.vertex_lineage_versions[vertex]

    def qem_edge_evaluation(self, edge: Edge) -> tuple[Vector3, float]:
        version = self.edge_versions.get(edge, 0)
        key = (edge, version)
        cached = self.qem_edge_cache.get(key)
        if cached is not None:
            return cached
        quadrics = self.vertex_quadrics()
        quadric = _sum_quadrics(quadrics[edge[0]], quadrics[edge[1]])
        placement = _optimal_qem_position(quadric, self.vertices[edge[0]], self.vertices[edge[1]])
        cost = _quadric_error(quadric, placement)
        result = (placement, cost)
        self.qem_edge_cache[key] = result
        return result

    def topology_version(self) -> int:
        return self._topology_version

    def vertex_neighbors(self, vertex: int, ring_depth: int = 1) -> set[int]:
        if vertex not in self.alive_vertices:
            return set()
        neighbors: set[int] = set()
        frontier = {vertex}
        visited = {vertex}
        for _ in range(max(0, ring_depth)):
            next_frontier: set[int] = set()
            for item in frontier:
                for edge in self.vertex_edges.get(item, set()):
                    next_frontier.update(edge)
            next_frontier.difference_update(visited)
            neighbors.update(next_frontier)
            visited.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break
        return neighbors

    def incident_faces(self, vertex: int) -> Sequence[Triangle]:
        return [
            triangle
            for face_id in self.vertex_faces.get(vertex, set())
            if (triangle := self.triangles.get(face_id)) is not None
        ]

    def bump_edge_version(self, edge: Edge) -> int:
        self.edge_versions[edge] += 1
        return self.edge_versions[edge]

    def is_current_edge(self, edge: Edge, version: int) -> bool:
        return (
            edge in self.edge_faces
            and edge[0] in self.alive_vertices
            and edge[1] in self.alive_vertices
            and self.edge_versions.get(edge, 0) == version
        )

    def affected_vertices(self, edge: Edge) -> set[int]:
        affected = set(edge)
        for face_id in self.edge_faces.get(edge, set()):
            affected.update(self.triangles.get(face_id, ()))
        for vertex in edge:
            for incident_edge in self.vertex_edges.get(vertex, set()):
                affected.update(incident_edge)
        return affected

    def edges_touching_any(self, vertices: set[int]) -> set[Edge]:
        edges: set[Edge] = set()
        for vertex in vertices:
            edges.update(self.vertex_edges.get(vertex, set()))
        return edges

    def conflict_scope(self, edge: Edge, ring_depth: int) -> tuple[set[int], set[int]]:
        key = (edge, self.edge_versions.get(edge, 0), ring_depth)
        cached = self.conflict_scope_cache.get(key)
        if cached is not None:
            vertices, faces = cached
            return set(vertices), set(faces)
        vertices = set(edge)
        frontier = set(edge)
        for _ in range(ring_depth):
            next_frontier: set[int] = set()
            for vertex in frontier:
                for incident_edge in self.vertex_edges.get(vertex, set()):
                    next_frontier.update(incident_edge)
            next_frontier.difference_update(vertices)
            vertices.update(next_frontier)
            frontier = next_frontier
            if not frontier:
                break

        faces: set[int] = set()
        for vertex in vertices:
            faces.update(self.vertex_faces.get(vertex, set()))
        for scoped_edge in self.edges_touching_any(vertices):
            faces.update(self.edge_faces.get(scoped_edge, set()))
        self.conflict_scope_cache[key] = (set(vertices), set(faces))
        return vertices, faces

    def can_collapse(self, edge: Edge, placement: Vector3) -> bool:
        if edge not in self.edge_faces:
            return False
        kept, removed = min(edge), max(edge)
        if kept not in self.alive_vertices or removed not in self.alive_vertices:
            return False
        edge_length = max(_distance(self.vertices[kept], self.vertices[removed]), 1e-12)
        if (
            _distance(placement, self.vertices[kept]) > edge_length * MAX_PLACEMENT_EDGE_LENGTH_MULTIPLIER
            or _distance(placement, self.vertices[removed]) > edge_length * MAX_PLACEMENT_EDGE_LENGTH_MULTIPLIER
        ):
            return False
        if self._would_break_boundary(edge, kept, removed):
            return False
        if self._would_flip_or_stretch_faces(kept, removed, placement, edge_length):
            return False
        return True

    def collapse(self, edge: Edge, cost: float, placement: Vector3) -> EdgeCollapseStep | None:
        if edge not in self.edge_faces:
            return None
        kept, removed = min(edge), max(edge)
        if kept not in self.alive_vertices or removed not in self.alive_vertices:
            return None

        before = self.triangle_count
        quadrics = self.vertex_quadrics()
        _add_quadric(quadrics[kept], quadrics[removed])
        quadrics[removed] = _zero_quadric()
        self.vertex_lineage[kept].update(self.vertex_lineage[removed])
        self.vertex_lineage[removed].clear()
        self.vertex_lineage_versions[kept] += 1
        self.vertex_lineage_versions[removed] += 1

        self.vertices[kept] = tuple(map(float, placement))
        self.alive_vertices.remove(removed)
        self._topology_version += 1

        affected_faces = set(self.vertex_faces.get(kept, set()))
        affected_faces.update(self.vertex_faces.get(removed, set()))
        for face_id in sorted(affected_faces):
            triangle = self.triangles.get(face_id)
            if triangle is None:
                continue
            self._remove_face_topology(face_id, triangle)
            rewritten = tuple(kept if vertex == removed else vertex for vertex in triangle)
            if len(set(rewritten)) == 3:
                new_triangle = rewritten  # type: ignore[assignment]
                self.triangles[face_id] = new_triangle
                self._add_face_topology(face_id, new_triangle)
            else:
                del self.triangles[face_id]

        removed_triangles = before - self.triangle_count
        if removed_triangles <= 0:
            return None
        return EdgeCollapseStep(
            edge=edge,
            kept_vertex=kept,
            removed_vertex=removed,
            cost=cost,
            placement=tuple(map(float, placement)),
            removed_triangle_count=removed_triangles,
            triangle_count=self.triangle_count,
        )

    def compact_vertices(self) -> list[Vector3]:
        used = sorted({vertex for triangle in self.triangles.values() for vertex in triangle})
        remap = {old: new for new, old in enumerate(used)}
        self._compact_remap = remap
        return [self.vertices[old] for old in used]

    def compact_triangles(self) -> list[Triangle]:
        remap = getattr(self, "_compact_remap", None)
        if remap is None:
            used = sorted({vertex for triangle in self.triangles.values() for vertex in triangle})
            remap = {old: new for new, old in enumerate(used)}
        return [
            (remap[triangle[0]], remap[triangle[1]], remap[triangle[2]])
            for _, triangle in sorted(self.triangles.items())
        ]

    def _build_initial_topology(self) -> None:
        self.edge_faces = defaultdict(set)
        self.vertex_edges = defaultdict(set)
        self.vertex_faces = defaultdict(set)
        for face_id, triangle in self.triangles.items():
            self._add_face_topology(face_id, triangle)

    def _add_face_topology(self, face_id: int, triangle: Triangle) -> None:
        for vertex in triangle:
            self.vertex_faces[vertex].add(face_id)
        for edge in _triangle_edges(triangle):
            self.edge_faces[edge].add(face_id)
            self.vertex_edges[edge[0]].add(edge)
            self.vertex_edges[edge[1]].add(edge)

    def _remove_face_topology(self, face_id: int, triangle: Triangle) -> None:
        for vertex in triangle:
            faces = self.vertex_faces.get(vertex)
            if faces is not None:
                faces.discard(face_id)
        for edge in _triangle_edges(triangle):
            faces = self.edge_faces.get(edge)
            if faces is None:
                continue
            faces.discard(face_id)
            if faces:
                continue
            del self.edge_faces[edge]
            for vertex in edge:
                edges = self.vertex_edges.get(vertex)
                if edges is not None:
                    edges.discard(edge)

    def _would_break_boundary(self, edge: Edge, kept: int, removed: int) -> bool:
        kept_boundary = self._is_boundary_vertex(kept)
        removed_boundary = self._is_boundary_vertex(removed)
        edge_is_boundary = len(self.edge_faces.get(edge, set())) == 1
        if kept_boundary != removed_boundary:
            return True
        if kept_boundary and not edge_is_boundary:
            return True
        return False

    def _is_boundary_vertex(self, vertex: int) -> bool:
        return any(len(self.edge_faces.get(edge, set())) == 1 for edge in self.vertex_edges.get(vertex, set()))

    def _would_flip_or_stretch_faces(
        self,
        kept: int,
        removed: int,
        placement: Vector3,
        collapsed_edge_length: float,
    ) -> bool:
        affected_faces = set(self.vertex_faces.get(kept, set()))
        affected_faces.update(self.vertex_faces.get(removed, set()))
        for face_id in affected_faces:
            triangle = self.triangles.get(face_id)
            if triangle is None:
                continue
            rewritten = tuple(kept if vertex == removed else vertex for vertex in triangle)
            if len(set(rewritten)) != 3:
                continue
            before_normal = _triangle_normal(
                self.vertices[triangle[0]],
                self.vertices[triangle[1]],
                self.vertices[triangle[2]],
            )
            new_positions = [
                placement if vertex == kept else self.vertices[vertex]
                for vertex in rewritten
            ]
            after_normal = _triangle_normal(new_positions[0], new_positions[1], new_positions[2])
            if before_normal is None or after_normal is None:
                return True
            if _dot(before_normal, after_normal) < MIN_NORMAL_DOT:
                return True
            for first, second in _triangle_edges(rewritten):
                first_position = placement if first == kept else self.vertices[first]
                second_position = placement if second == kept else self.vertices[second]
                if _distance(first_position, second_position) > collapsed_edge_length * MAX_NEW_EDGE_LENGTH_MULTIPLIER:
                    return True
        return False


def _valid_triangle(triangle: Sequence[int], vertex_count: int) -> Triangle | None:
    if len(triangle) != 3:
        return None
    a, b, c = int(triangle[0]), int(triangle[1]), int(triangle[2])
    if a == b or b == c or a == c:
        return None
    if min(a, b, c) < 0 or max(a, b, c) >= vertex_count:
        return None
    return a, b, c


def _triangle_edges(triangle: Triangle) -> tuple[Edge, Edge, Edge]:
    a, b, c = triangle
    return _edge(a, b), _edge(b, c), _edge(c, a)


def _edge_afcost_signals(
    edge: Edge,
    mesh_state: MeshState,
    eps: float,
    vertex_signal_cache: dict[tuple[int, int, int], tuple[float, float]],
) -> _AFCostSignals:
    _, qem_cost = mesh_state.qem_edge_evaluation(edge)
    qem_log = -math.log(max(float(eps) + max(0.0, qem_cost), float(eps)))
    vertex_signals = [
        _vertex_local_pd_signal(vertex, mesh_state, vertex_signal_cache)
        for vertex in edge
    ]
    persistence = max(signal[0] for signal in vertex_signals) if vertex_signals else 0.0
    tiny_detail = max(signal[1] for signal in vertex_signals) if vertex_signals else 0.0
    return _AFCostSignals(
        qem_log=qem_log,
        persistence=persistence,
        tiny_detail=tiny_detail,
        qem_cost=qem_cost,
    )


def _vertex_local_pd_signal(
    vertex: int,
    mesh_state: MeshState,
    cache: dict[tuple[int, int, int], tuple[float, float]],
) -> tuple[float, float]:
    key = (id(mesh_state), mesh_state.topology_version(), vertex)
    cached = cache.get(key)
    if cached is not None:
        return cached

    ring1 = mesh_state.vertex_neighbors(vertex, 1)
    ring2 = mesh_state.vertex_neighbors(vertex, 2)
    scoped_vertices = {vertex}
    scoped_vertices.update(ring2)
    normal_variation = {
        item: _vertex_normal_variation(item, mesh_state)
        for item in scoped_vertices
    }
    h0 = normal_variation.get(vertex, 0.0)
    h1 = _average_values(normal_variation, ring1)
    h2 = _average_values(normal_variation, ring2 - ring1)
    small_response = abs(h0 - h1)
    larger_response = abs(h1 - h2)
    persistence = min(small_response, larger_response) + 0.5 * larger_response
    tiny_detail = max(0.0, small_response - larger_response)
    result = (persistence, tiny_detail)
    cache[key] = result
    return result


def _vertex_normal_variation(vertex: int, mesh_state: MeshState) -> float:
    normals = []
    for triangle in mesh_state.incident_faces(vertex):
        normal = _triangle_normal(
            mesh_state.vertices[triangle[0]],
            mesh_state.vertices[triangle[1]],
            mesh_state.vertices[triangle[2]],
        )
        if normal is not None:
            normals.append(normal)
    if len(normals) < 2:
        return 0.0
    average = _normalize_vector(
        (
            sum(normal[0] for normal in normals),
            sum(normal[1] for normal in normals),
            sum(normal[2] for normal in normals),
        )
    )
    if average is None:
        return 0.0
    return sum(_angle_between(average, normal) for normal in normals) / len(normals) / math.pi


def _average_values(values: dict[int, float], keys: set[int]) -> float:
    if not keys:
        return 0.0
    collected = [values.get(key, 0.0) for key in keys]
    return sum(collected) / len(collected) if collected else 0.0


def _edge(a: int, b: int) -> Edge:
    return (a, b) if a < b else (b, a)


def _midpoint(a: Vector3, b: Vector3) -> Vector3:
    return (
        (a[0] + b[0]) * 0.5,
        (a[1] + b[1]) * 0.5,
        (a[2] + b[2]) * 0.5,
    )


def _is_finite_vector(vector: Vector3) -> bool:
    return all(math.isfinite(value) for value in vector)


def _zero_quadric() -> list[list[float]]:
    return [[0.0 for _ in range(4)] for _ in range(4)]


def _vertex_quadrics(vertices: Sequence[Vector3], triangles: Sequence[Triangle]) -> list[list[list[float]]]:
    quadrics = [_zero_quadric() for _ in vertices]
    for triangle in triangles:
        plane = _plane_from_triangle(vertices[triangle[0]], vertices[triangle[1]], vertices[triangle[2]])
        if plane is None:
            continue
        face_quadric = [[plane[row] * plane[col] for col in range(4)] for row in range(4)]
        for vertex_index in triangle:
            _add_quadric(quadrics[vertex_index], face_quadric)
    return quadrics


def _add_quadric(target: list[list[float]], source: list[list[float]]) -> None:
    for row in range(4):
        for col in range(4):
            target[row][col] += source[row][col]


def _sum_quadrics(first: Sequence[Sequence[float]], second: Sequence[Sequence[float]]) -> list[list[float]]:
    return [[first[row][col] + second[row][col] for col in range(4)] for row in range(4)]


def _quadric_error(quadric: Sequence[Sequence[float]], position: Vector3) -> float:
    vector = (position[0], position[1], position[2], 1.0)
    total = 0.0
    for row in range(4):
        for col in range(4):
            total += vector[row] * quadric[row][col] * vector[col]
    return max(0.0, float(total))


def _plane_from_triangle(a: Vector3, b: Vector3, c: Vector3) -> tuple[float, float, float, float] | None:
    normal = _cross(_sub(b, a), _sub(c, a))
    length = _length(normal)
    if length <= 1e-12:
        return None
    nx, ny, nz = normal[0] / length, normal[1] / length, normal[2] / length
    d = -(nx * a[0] + ny * a[1] + nz * a[2])
    return nx, ny, nz, d


def _optimal_qem_position(quadric: Sequence[Sequence[float]], v0: Vector3, v1: Vector3) -> Vector3:
    midpoint = _midpoint(v0, v1)
    segment_position = _segment_minimum_qem_position(quadric, v0, v1)
    candidates = (v0, v1, midpoint, segment_position)

    matrix = (
        (quadric[0][0], quadric[0][1], quadric[0][2]),
        (quadric[1][0], quadric[1][1], quadric[1][2]),
        (quadric[2][0], quadric[2][1], quadric[2][2]),
    )
    rhs = (-quadric[0][3], -quadric[1][3], -quadric[2][3])
    solved = _solve_3x3(matrix, rhs)
    if solved is not None and _point_lies_on_segment(solved, v0, v1):
        candidates = (*candidates, solved)
    return min(candidates, key=lambda position: _quadric_error(quadric, position))


def _segment_minimum_qem_position(
    quadric: Sequence[Sequence[float]],
    v0: Vector3,
    v1: Vector3,
) -> Vector3:
    direction = _sub(v1, v0)
    homogeneous_origin = (v0[0], v0[1], v0[2], 1.0)
    homogeneous_direction = (direction[0], direction[1], direction[2], 0.0)
    denominator = 0.0
    numerator = 0.0
    for row in range(4):
        for col in range(4):
            denominator += homogeneous_direction[row] * quadric[row][col] * homogeneous_direction[col]
            numerator += homogeneous_direction[row] * quadric[row][col] * homogeneous_origin[col]
    if abs(denominator) <= 1e-12:
        t = 0.5
    else:
        t = -numerator / denominator
    t = max(0.0, min(1.0, float(t)))
    return (
        v0[0] + direction[0] * t,
        v0[1] + direction[1] * t,
        v0[2] + direction[2] * t,
    )


def _point_lies_on_segment(point: Vector3, v0: Vector3, v1: Vector3) -> bool:
    edge = _sub(v1, v0)
    edge_length_squared = _dot(edge, edge)
    if edge_length_squared <= 1e-24:
        return False
    relative = _sub(point, v0)
    t = _dot(relative, edge) / edge_length_squared
    if t < -1e-6 or t > 1.0 + 1e-6:
        return False
    projection = (
        v0[0] + edge[0] * t,
        v0[1] + edge[1] * t,
        v0[2] + edge[2] * t,
    )
    edge_length = math.sqrt(edge_length_squared)
    return _distance(point, projection) <= max(edge_length * 1e-5, 1e-8)


def _solve_3x3(matrix: Sequence[Sequence[float]], rhs: Vector3) -> Vector3 | None:
    determinant = _det3(matrix)
    if abs(determinant) <= 1e-12:
        return None
    mx = (
        (rhs[0], matrix[0][1], matrix[0][2]),
        (rhs[1], matrix[1][1], matrix[1][2]),
        (rhs[2], matrix[2][1], matrix[2][2]),
    )
    my = (
        (matrix[0][0], rhs[0], matrix[0][2]),
        (matrix[1][0], rhs[1], matrix[1][2]),
        (matrix[2][0], rhs[2], matrix[2][2]),
    )
    mz = (
        (matrix[0][0], matrix[0][1], rhs[0]),
        (matrix[1][0], matrix[1][1], rhs[1]),
        (matrix[2][0], matrix[2][1], rhs[2]),
    )
    return _det3(mx) / determinant, _det3(my) / determinant, _det3(mz) / determinant


def _det3(matrix: Sequence[Sequence[float]]) -> float:
    return (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )


def _sub(a: Vector3, b: Vector3) -> Vector3:
    return a[0] - b[0], a[1] - b[1], a[2] - b[2]


def _cross(a: Vector3, b: Vector3) -> Vector3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Vector3, b: Vector3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(vector: Vector3) -> float:
    return math.sqrt(vector[0] * vector[0] + vector[1] * vector[1] + vector[2] * vector[2])


def _normalize_vector(vector: Vector3) -> Vector3 | None:
    length = _length(vector)
    if length <= 1e-12:
        return None
    return vector[0] / length, vector[1] / length, vector[2] / length


def _angle_between(a: Vector3, b: Vector3) -> float:
    return math.acos(max(-1.0, min(1.0, _dot(a, b))))


def _distance(a: Vector3, b: Vector3) -> float:
    return _length(_sub(a, b))


def _mesh_diagonal_squared(vertices: Sequence[Vector3]) -> float:
    if not vertices:
        return 1.0
    xs = [vertex[0] for vertex in vertices]
    ys = [vertex[1] for vertex in vertices]
    zs = [vertex[2] for vertex in vertices]
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    dz = max(zs) - min(zs)
    diagonal_squared = dx * dx + dy * dy + dz * dz
    return diagonal_squared if diagonal_squared > 1e-12 else 1.0


def _triangle_normal(a: Vector3, b: Vector3, c: Vector3) -> Vector3 | None:
    normal = _cross(_sub(b, a), _sub(c, a))
    length = _length(normal)
    if length <= 1e-12:
        return None
    return normal[0] / length, normal[1] / length, normal[2] / length
