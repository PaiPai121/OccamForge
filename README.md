# AssetForge

AssetForge is a desktop pipeline application for turning Blender vehicle models into game-ready assets. Phase 1 focuses on a maintainable foundation and vehicle structure analysis.

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

CLI analysis:

```powershell
assetforge-analyze .\RhinoTank.blend --json .\analysis-report.json
```

CLI optimization:

```powershell
assetforge-optimize .\RhinoTank.blend --profile generic_vehicle --target-triangles 5000 --json .\optimization-report.json
```

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

The build output is written to `build/`:

- `<name>_cs.fbx`
- `<name>_cs_d.png`
- `build_report.json`

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
