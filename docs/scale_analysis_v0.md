# Scale Analysis V0

Scale Analysis V0 is an AssetForge V2 Alpha research prototype for scale-first
visual importance simplification. It analyzes a single mesh object and produces
heatmaps and a JSON report. It does not reduce triangles, collapse edges, or
rewrite topology.

## Why QEM Cost Is Not Visual Importance

Quadric Error Metrics estimate the geometric error introduced by a candidate
edge collapse. That makes QEM useful as a local simplification executor, but it
does not answer the higher-level question of which visual structures matter.

A low QEM cost can still belong to a recognizable contour or repeated design
feature if the local plane error is small. A high QEM cost can belong to a tiny
bolt, bevel, hole, or scratch that is geometrically sharp but visually
expendable at game scale. QEM is local and collapse-specific; visual importance
is contextual and scale-dependent.

For AssetForge V2, QEM should therefore be treated as an executor: once a region
has been identified as safe to simplify, QEM can choose locally reasonable edge
collapses. It should not be the primary importance signal.

## Why Mesh Saliency Can Still Misread Details

Mesh Saliency introduced a useful center-surround idea: compare local geometric
signals across scales and mark vertices that stand out from their surroundings.
That is closer to visual perception than raw QEM cost, but saliency alone can
still overvalue small manufactured details.

Wheel bolts, small holes, hard bevels, vents, and tiny raised plates can produce
strong local curvature or normal contrast. A saliency detector may mark them as
important because they are locally distinctive, even if they disappear quickly as
the observation scale grows. For AssetForge, those are often the exact details
that should be reduced first.

## Core Hypothesis

Scale Analysis V0 uses one working assumption:

Only features that exist at small scale are detail; features that persist across
multiple scales are structure.

In practice, the analyzer estimates a normal-variation field around each vertex,
samples that field at increasing radii, then measures center-surround response
between adjacent scales. A response that exists only at the smallest scales is a
candidate tiny detail. A response that remains active across several scales is a
candidate structure.

## Theory Sources

Scale Analysis V0 is based on three ideas:

- Scale-space and multi-scale feature detection: evaluate the same signal at
  multiple observation radii rather than relying on one local measurement.
- Mesh Saliency center-surround comparison: compare near-scale and wider-scale
  responses to detect geometry that stands out.
- QEM as executor, not importance: use multi-scale analysis to decide what is
  visually important, then use QEM later only for local simplification mechanics.

## V0 Input Assumptions

- In the GUI workflow, Scale Analysis runs on the preprocessed blend file.
- Preprocess joins all mesh objects into one `*_Model` mesh before analysis.
- CLI can still target a single object with `--object-name` for experiments.
- The mesh is a triangle mesh after Blender evaluation.
- Multi-object semantic segmentation is out of scope; the joined model is treated
  as one geometry set.
- Existing materials, UV islands, seams, and texture information are not used.
- The result is diagnostic; it is not a production reduction pass.

## V0 Output

Scale Analysis V0 outputs:

- Per-vertex `scale_persistence`, normalized to 0..1.
- Per-vertex `tiny_detail_score`, normalized to 0..1.
- `scale_persistence_heatmap.png`.
- `tiny_detail_heatmap.png`.
- `scale_analysis_report.json`.

## Algorithm V0

1. Compute model bounding-box diagonal `D`.
2. Use default scales `[0.005D, 0.01D, 0.02D, 0.04D, 0.08D]` unless overridden.
3. Compute per-vertex local normal variation from adjacent triangle normals.
4. For every scale radius `r`, average nearby vertices' normal variation:
   `R(v, r)`.
5. For adjacent scales, compute center-surround response:
   `S(v, r) = abs(R(v, r) - R(v, 2r))`.
6. Use each response scale's 75th percentile as the V0 threshold.
7. Compute `scale_persistence` from the count of active responses.
8. Compute `tiny_detail_score` when the response is strong at the smallest scale
   and weak at later scales.

## Heatmap Meaning

`scale_persistence_heatmap.png`:

- Blue means low persistence and likely small-scale detail.
- Red means high persistence and likely larger structure.

`tiny_detail_heatmap.png`:

- Red means likely removable tiny detail.
- Blue means not classified as tiny detail.

## Current Limits

V0 is intentionally simple. It uses geometry only, does not understand semantic
parts, and may need threshold tuning for dense CAD meshes, very sparse meshes, or
meshes with uneven vertex density. It is a research probe for scale-first visual
importance, not a simplification executor.

## Center-Surround Heatmap

The explicit center-surround response is:

```text
S(v, sigma) = |G(H, sigma) - G(H, 2sigma)|
```

Where `H` is the mean-curvature signal. In V0, `H` is approximated by adjacent
triangle normal variation at each vertex. `G(H, sigma)` is the radius-smoothed
curvature signal around vertex `v`.

The subtraction asks: how different is this local area from its wider
surrounding context? A high value means the region stands out from the larger
background at that scale.

The software view now emits four heatmaps:

- `mean_curvature_heatmap.png`: raw local normal-variation curvature proxy `H`; this is a vertex signal projected onto mesh edges for visualization, not an edge-collapse cost.
- `center_surround_heatmap.png`: strongest center-surround response across
  adjacent scales.
- `scale_persistence_heatmap.png`: how many scales remain active.
- `tiny_detail_heatmap.png`: strongest when response appears only at the
  smallest scales.
