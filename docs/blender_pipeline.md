# Blender Vehicle Analysis Pipeline

## Current Analyzer

The Phase 1 analyzer opens the selected `.blend` file in Blender background mode and inspects mesh objects in the active scene.

Detected objects:

- body: exact mesh object name `VehicleBody`
- wheels: mesh object names matching `Wheel_\d+`
- fallback wheels: mesh names starting with `wheel` or common misspelling `whell`
- fallback body: if exactly one mesh object is not wheel-like and wheel-like meshes exist, that object is inferred as the vehicle body

Reported metrics:

- mesh object count
- total vertices
- total loop triangles
- wheel count
- warnings
- errors

## Notes

Triangle counts use Blender mesh loop triangles after calling `calc_loop_triangles()`. This gives a game-pipeline-friendly triangle estimate without modifying the source file.

Fallback classification is reported through warnings so users can see when AssetForge inferred structure from imperfect naming instead of exact conventions.

## Optimization

Phase 2 optimization runs only on a copy named `<source>_optimized.blend`.

Current rules:

- open the original file
- copy it before modifying
- detect body and wheels with the same analyzer fallback rules
- apply rotation and scale transforms to mesh objects
- count original triangles after transforms
- preserve wheel objects
- preserve object hierarchy by avoiding joins or object reconstruction
- add a Decimate modifier to the body object
- iteratively adjust the Decimate ratio until the target is reached or the profile limit is hit
- save the optimized `.blend`
- save `<source>_optimized_report.json`

Optimization settings come from `AssetProfile` values such as `generic_vehicle` and `cities_skylines_vehicle`, with the GUI target triangle field overriding the profile default for a single run.

## FBX Export

Phase 3 export lets a user complete:

```text
.blend -> Analyze -> Optimize -> Export FBX
```

without opening Blender.

Current rules:

- analyze before export
- prefer `<source>_optimized.blend` when it exists
- export to `<source>_cs.fbx`
- apply transforms in Blender memory before export
- use Cities Skylines friendly defaults: selected mesh export, unit scale applied, `-Z` forward, `Y` up, mesh modifiers enabled, no leaf bones
- keep `.blend` files unchanged during export

The GUI validation panel shows triangle count, wheel count, object count, Blender path, and export readiness.

## Validation And Preview

Phase 4 validation runs without exporting. It opens the selected `.blend` in Blender background mode and writes `validation_report.json` beside the asset.

Checks:

- triangle count against the selected `AssetProfile`
- wheel count
- body detection
- unapplied transforms
- object count
- missing image textures
- missing LOD markers

For `cities_skylines_vehicle`:

- preferred: triangles under 5000
- warning: triangles over 10000
- critical: triangles over 20000

The report includes a 0-100 compatibility score and an asset readiness rating: `Excellent`, `Good`, `Warning`, or `Critical`.

The Preview panel is generated from validation output and shows detected body, detected wheels, and unknown objects. Selecting an item highlights it in the list and updates the status text.

Validation reports include an `import_readiness` section with generated package paths, file readiness, Cities Skylines Asset Editor status, and manual import steps.

## One-Click Cities Skylines Build

Phase 5 adds a beginner-friendly build path:

```text
.blend -> Build Cities Skylines Asset -> build package
```

The build runs in Blender background mode and does not require the user to open Blender.

Workflow:

- analyze and classify body/wheels
- optimize automatically when triangles exceed the Cities Skylines target
- Smart UV Project all mesh objects
- create a 1024x1024 diffuse texture
- bake Blender material diffuse colors
- export FBX with Cities Skylines friendly defaults
- export the Cities Skylines FBX as a single joined mesh from a temporary export scene
- write `build/build_report.json`

Outputs:

- `build/<source>_cs.fbx`
- `build/<source>_cs_d.png`
- `build/build_report.json`

Validation now treats missing image textures as `Can Auto Generate Texture`, because the build workflow can produce `_cs_d.png` automatically.
