# OccamForge

OccamForge is an open-source desktop tool for turning Blender models into game-ready assets. The current release focuses on a practical Blender to Cities: Skylines workflow with candidate-aware triangle reduction, visual review stages, texture baking, and one-click FBX package generation.

The app runs Blender in background mode for model analysis and mesh processing, while the desktop UI is built with PySide6 Qt WebEngine.

## Current Features

- Select `.blend` models from a desktop GUI
- Auto Safe Preprocess with conservative Limited Dissolve cleanup
- View the current model preview after import, cleanup, and optimization
- Generate Geometry Report data for `.blend`, `.obj`, `.fbx`, `.glb`, and `.gltf`
- Identify optimization candidates from density, curvature, surface area, and silhouette contribution
- Review staged optimization with heatmaps and stage reports
- Run candidate-aware reduction stages instead of a single global decimate
- Preserve original materials when generating debug heatmaps, so baked textures keep color
- Build Cities: Skylines import files:
  - single-mesh FBX
  - `_d.png` diffuse texture
  - optional deployment to the Cities: Skylines Import folder

## Release Status

`v1.0.0` is the first public milestone release. It is usable for the tested Blender to Cities: Skylines path, but the optimizer is still evolving. Very aggressive targets such as 3,000 triangles may require manual review because preserving the main silhouette is currently prioritized over forcing the triangle count.

## Requirements

- Windows
- Python 3.11+
- Blender installed locally
- `uv` recommended, standard `pip` also works

Set Blender path if it is not on `PATH`:

```powershell
$env:OCCAMFORGE_BLENDER_PATH="C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"
```

Legacy `ASSETFORGE_BLENDER_PATH` is still accepted for compatibility.

OccamForge also auto-discovers Blender in this order:

1. Saved user configuration
2. Windows Start Menu shortcuts
3. `PATH`
4. Windows Registry uninstall entries
5. Steam libraries
6. Manual Browse dialog in the GUI

Valid Blender paths are verified with `blender.exe --version` and saved to:

```text
%APPDATA%\OccamForge\config.json
```

## Setup

```powershell
git clone https://github.com/PaiPai121/OccamForge.git
cd OccamForge
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
occamforge
```

The legacy `assetforge` command is also available for compatibility.

Recommended GUI flow:

```text
Select Model File
-> Auto Safe Preprocess
-> Review / Analyze optimization candidates
-> Apply staged optimization if needed
-> Build Cities Skylines Asset
```

## CLI

Analyze a Blender model:

```powershell
occamforge-analyze .\RhinoTank.blend --json .\analysis-report.json
```

Run Safe Preprocess:

```powershell
occamforge-preprocess .\RhinoTank.blend --angle-degrees 1.0 --json .\RhinoTank_preprocessed_report.json
```

Generate a Geometry Report:

```powershell
occamforge-geometry-report .\RhinoTank.blend --output .\geometry_reports --json .\geometry_reports\geometry-report.json
```

Generate a real staged optimization preview:

```powershell
occamforge-real-preview .\RhinoTank.blend --target-triangles 3000 --pipeline-stage 3 --output .\previews --json .\previews\real-preview-report.json
```

Compare original and optimized geometry:

```powershell
occamforge-simplification-report .\RhinoTank.blend --optimized-blend .\previews\preview_3000.blend --output .\simplification_reports
```

Build a Cities: Skylines asset package:

```powershell
occamforge-build-cs .\RhinoTank.blend --json .\build-report.json
```

Legacy `assetforge-*` command names are still registered.

## Optimization Pipeline

### Auto Safe Preprocess

Safe Preprocess creates `<name>_preprocessed.blend` and runs a conservative Limited Dissolve pass on a copy. It does not modify the original file and does not chase a target triangle count.

### Geometry Report

Geometry Report does not edit the model. It identifies where triangle budget is spent and produces structured optimization candidates:

- `MUST_KEEP`
- `SOFT_KEEP`
- `REDUCE_FIRST`
- `DELETE_CANDIDATE`

The report considers density, surface area, curvature, and silhouette contribution.

### Stage 1: Conservative Candidate-Aware Reduce

Stage 1 applies conservative reduction using the candidate report. It protects important silhouette and structure regions and stops before destructive reduction.

### Stage 2: Aggressive Reduce

Stage 2 is split into:

- `2A Structural Protection Expansion`
- `2B Detail Candidate Detection`
- `2C Bucket-Based Controlled Decimate`
- `2D Local Fallback`

This stage prioritizes keeping the main body shape before reducing lower-importance regions.

### Stage 3: Detail Suppression

Stage 3 targets low-visibility small details, bevel strips, repeated details, rings, and other high-density surface features. It uses localized delete/dissolve operations and preserves original material assignments after debug heatmaps are rendered.

## Output Files

Build output is written to `build/`:

- `<name>_cs.fbx`
- `<name>_cs_d.png`
- `build_report.json`

Preview output is written to `previews/`:

- `preview_<target>.blend`
- `preview_<target>.png`
- stage reports and heatmaps

Geometry and simplification reports are written to:

- `geometry_reports/`
- `simplification_reports/`

## Architecture

The GUI depends on application services, not Blender internals. Blender execution is isolated in `assetforge.blender`.

```text
src/assetforge/
  app/       composition root and entry points
  gui/       PySide6 Web UI and Qt workers
  core/      config and logging
  domain/    dataclasses and business concepts
  blender/   Blender subprocess adapter and in-Blender scripts
  services/  application use cases and ports
  models/    DTO serialization
tests/       unit tests
docs/        architecture and pipeline notes
examples/    example output
```

The internal Python package is still named `assetforge` for compatibility with earlier milestones. Public project metadata and CLI aliases use OccamForge.

## Development

Run tests:

```powershell
pytest
```

Package the desktop executable:

```powershell
python -m PyInstaller AssetForge.spec --noconfirm
```

Current executable output:

```text
dist\AssetForge\AssetForge.exe
```

The executable name will be renamed in a future packaging cleanup.

## Friendship Link
俺也在这里发了帖
https://linux.do/


## License

MIT License. See [LICENSE](LICENSE).
