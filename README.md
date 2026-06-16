# AssetForge

AssetForge is a desktop pipeline application for turning Blender vehicle models into game-ready assets. Phase 1 focuses on a maintainable foundation and vehicle structure analysis.

The desktop shell now uses a Web UI inside PySide6 Qt WebEngine. Python still owns the Blender pipeline, while HTML/CSS/JavaScript owns the user-facing workflow.

## Phase 1 Features

- Select a `.blend` file from a PySide6 desktop GUI.
- Run Blender in background mode.
- Detect `VehicleBody`.
- Detect `Wheel_001`, `Wheel_002`, `Wheel_003`, and other `Wheel_*` numbered mesh objects.
- Count mesh objects, vertices, triangles, and wheels.
- Display warnings, errors, progress, and output logs.

## Requirements

- Python 3.11+
- Blender installed locally
- `uv` recommended, standard `pip` also works

Set Blender path if it is not on `PATH`:

```powershell
$env:ASSETFORGE_BLENDER_PATH="C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"
```

AssetForge also auto-discovers Blender in this order:

1. Saved user configuration
2. Windows Start Menu shortcuts
3. `PATH`
4. Windows Registry uninstall entries
5. Steam libraries
6. Manual Browse dialog in the GUI

Valid Blender paths are verified with `blender.exe --version` and saved to:

```text
%APPDATA%\AssetForge\config.json
```

AssetForge does not scan drives during normal startup.

## Setup

```powershell
cd D:\work_console\AssetForge
uv venv
.\.venv\Scripts\Activate.ps1
uv pip install -e ".[dev]"
```

Without `uv`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Run

```powershell
assetforge
```

The main screen is a guided workflow:

- select a `.blend` file for the full vehicle build workflow
- select `.blend`, `.obj`, `.fbx`, `.glb`, or `.gltf` for Geometry Report analysis
- inspect the model information and viewport preview
- optionally run Safe Preprocess to clean low-risk coplanar geometry
- optionally enable triangle optimization and choose a maximum triangle count
- optionally generate one real optimization preview
- apply the preview target
- build the Cities Skylines package

CLI analysis:

```powershell
assetforge-analyze .\RhinoTank.blend --json .\analysis-report.json
```

CLI optimization:

```powershell
assetforge-optimize .\RhinoTank.blend --profile generic_vehicle --target-triangles 5000 --json .\optimization-report.json
```

CLI real optimization preview:

```powershell
assetforge-real-preview .\RhinoTank.blend --target-triangles 15000 --output .\previews --json .\previews\real-preview-report.json
```

CLI safe preprocess:

```powershell
assetforge-preprocess .\RhinoTank.blend --angle-degrees 1.0 --json .\RhinoTank_preprocessed_report.json
```

Safe Preprocess creates `<name>_preprocessed.blend` and runs a conservative Limited Dissolve pass on the copy. It does not modify the original file. In the GUI, once Safe Preprocess succeeds, the next real preview or Cities Skylines build uses the preprocessed copy automatically.

CLI geometry report:

```powershell
assetforge-geometry-report .\RhinoTank.blend --output .\geometry_reports --json .\geometry_reports\geometry-report.json
```

Geometry Report runs before optimization and does not modify, optimize, export, or build the model. It answers where the triangle budget is being spent for `.blend`, `.obj`, `.fbx`, `.glb`, and `.gltf` inputs.

Geometry output is written to `geometry_reports/`:

- `geometry_report.json`
- `geometry_report.png`

The heatmap colors mean:

- blue: low triangle density
- green: medium triangle density
- yellow: high triangle density
- red: extreme triangle density

CLI simplification report:

```powershell
assetforge-simplification-report .\RhinoTank.blend --optimized-blend .\RhinoTank_optimized.blend --output .\simplification_reports
```

If `--optimized-blend` is omitted, AssetForge compares against `<source>_optimized.blend`. Simplification Analysis does not optimize or export; it compares the existing original and optimized files.

Simplification output is written to `simplification_reports/`:

- `simplification_report.json`
- `simplification_heatmap.png`

The simplification heatmap colors mean:

- green: little simplification
- yellow: medium simplification
- red: heavy simplification

CLI FBX export:

```powershell
assetforge-export-fbx .\RhinoTank.blend --profile cities_skylines_vehicle --json .\export-report.json
```

Strict single-mesh FBX experiment:

```powershell
assetforge-export-fbx-strict .\RhinoTank.blend --json .\strict-export-report.json
```

Cities Skylines export uses a single joined mesh by default because the Asset Editor rejected the earlier multi-mesh FBX.

CLI validation:

```powershell
assetforge-validate .\RhinoTank.blend --profile cities_skylines_vehicle --json .\validation-report.json
```

One-click Cities Skylines build:

```powershell
assetforge-build-cs .\RhinoTank.blend --json .\build-report.json
```

By default, the build preserves the original mesh triangle count. To reduce triangles during build, enable `Optimize triangle count` in the GUI or pass `--optimize --target-triangles <count>` in the CLI.

Recommended GUI flow:

```text
Select Model File -> Safe Preprocess -> optional Optimize triangle count -> Build Cities Skylines Asset
```

The build output is written to `build/`:

- `<name>_cs.fbx`
- `<name>_cs_d.png`
- `build_report.json`

When a Cities Skylines Import folder is configured, AssetForge deploys only the game-facing files there: `<name>_cs.fbx` and `<name>_cs_d.png`. Internal `.blend` copies and reports stay in `build/`.

Texture suffixes follow common Cities Skylines asset naming:

- `_d`: diffuse/albedo color texture, generated now as `<name>_cs_d.png`
- `_n`: normal map, planned for future support
- `_s`: specular map, planned for future support
- `_i`: illumination/emissive map, planned for future support

Optimization preview:

- Quality presets: `Fast`, `Balanced`, `High Quality`
- Advanced target triangle slider
- Editable preview targets, defaulting to `5000`, `10000`, `15000`, `25000`
- Preview comparisons also include the current slider target
- Displays estimated triangles, reduction percentage, and compatibility score before building

Real optimization preview:

- `Generate Real Preview` runs Blender in the background
- uses the current `Target Triangles` value
- creates one real optimized preview `.blend`
- renders one 512x512 PNG thumbnail with an automatic camera and light
- shows original triangles, target triangles, actual triangles, reduction percentage, compatibility score, and rating
- `Apply Current Preview` copies the preview target back into the Optimize target field and slider
- if the model is already below the target, AssetForge skips optimization and reports `Model already satisfies target triangle limit.`

Preview output is written to `previews/` by default:

- `preview_<target>.blend`
- `preview_<target>.png`
- `real_preview_report.json`

If `RhinoTank_optimized.blend` exists beside the selected source file, AssetForge exports that optimized copy while writing `RhinoTank_cs.fbx`.

## Naming Convention

AssetForge expects:

- `VehicleBody`
- `Wheel_001`
- `Wheel_002`
- `Wheel_003`
- additional wheels matching `Wheel_<number>`

Real-world fallback detection also recognizes wheel-like names starting with `wheel` or common misspelling `whell`. If exactly one mesh object is not wheel-like, AssetForge infers it as the body and reports that as a warning.

## Architecture

The GUI depends on application services, not Blender. Blender execution is isolated in `assetforge.blender`.

```text
src/assetforge/
  app/       composition root and entry points
  gui/       PySide6 UI and Qt workers
  core/      config and logging
  domain/    dataclasses and business concepts
  blender/   Blender subprocess adapter and in-Blender scripts
  services/  application use cases and ports
  models/    DTO serialization
tests/       unit tests
scripts/     developer helper scripts
docs/        architecture and pipeline notes
examples/    example output
```

Planned features such as optimization, LODs, baking, FBX export, and game-specific exporters should be added behind service interfaces and adapter implementations.
