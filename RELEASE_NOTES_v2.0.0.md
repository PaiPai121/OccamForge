# OccamForge v2.0.0

This release moves OccamForge from the v1 rule-based reduction workflow toward the v2 cost-based diagnostics and local edge-collapse path.

## Highlights

- Adds CollapseImpact diagnostics for simulated edge collapse after-change.
- Splits CollapseImpact into independent metrics:
  - `normal_impact`
  - `area_impact`
  - `edge_length_impact`
  - `removed_face_ratio`
- Uses `normal_impact` as the default GUI heatmap.
- Keeps `combined_experimental_impact` hidden and marked experimental.
- Adds a main-window `Collapse Impact` button for running the diagnostic directly.
- Integrates CollapseImpact with the Heatmap Diagnostics flow before AFCost candidate generation.
- Adds CLI entry points:
  - `occamforge-collapse-impact`
  - `assetforge-collapse-impact`

## Validation

- `pytest`: 81 passed
- Rhino Tank CollapseImpact service smoke run: 90,464 edges analyzed
