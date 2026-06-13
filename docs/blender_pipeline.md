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
