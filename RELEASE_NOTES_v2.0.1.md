# OccamForge v2.0.1

Patch release for the v2 cost-based workflow.

## Fixes

- Fixes repeated local collapse runs with different AFCost candidates reusing the same output paths.
- Keeps AFCost-specific local simplification outputs separate, for example `afcost_00` and `afcost_02`.
- Fixes Cities Skylines texture export after local collapse by exporting only the baked UV layer.
- Binds the generated `_cs_d.png` diffuse texture explicitly to the exported FBX material.

## Validation

- `pytest`: 81 passed
- User verified the rebuilt executable against the texture issue.
