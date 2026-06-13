# Release Candidate Validation Workflow

This workflow validates the complete Blender -> AssetForge -> Cities Skylines pipeline before new functionality is added.

## Automated Preflight

Run:

```powershell
assetforge-build-cs .\rhino_tank.blend --json .\examples\rhino_tank_build_report.json
```

Expected package:

- `build\rhino_tank_cs.fbx`
- `build\rhino_tank_cs_d.png`
- `build\build_report.json`

Run FBX smoke import through Blender:

```powershell
& "D:\SteamLibrary\steamapps\common\Blender\blender.exe" --background --python .\scripts\blender_fbx_import_smoke.py -- --fbx .\build\rhino_tank_cs.fbx --output-json .\examples\rhino_tank_fbx_import_smoke.json
```

## Import Test Checklist

- [ ] FBX loads
- [ ] Model orientation correct
- [ ] Scale correct
- [ ] Wheels detected
- [ ] Texture loads
- [ ] No missing materials
- [ ] Asset saves successfully

## Manual Cities Skylines Steps

1. Open Cities Skylines.
2. Open `Tools > Asset Editor`.
3. Choose the appropriate vehicle template.
4. Import `build\rhino_tank_cs.fbx`.
5. Confirm or assign `build\rhino_tank_cs_d.png` as the diffuse texture.
6. Inspect orientation and scale.
7. Confirm wheel placement and wheel recognition.
8. Confirm no missing materials are shown.
9. Save the asset.

## Current Boundary

AssetForge can generate the package and run automated file/FBX smoke checks. Cities Skylines Asset Editor validation remains manual because the editor is an interactive game workflow without a reliable headless import API.

## Single-Mesh Cities Skylines Export

The strict single-mesh experiment showed that Cities Skylines accepts a single-mesh FBX while the previous multi-mesh FBX kept `Continue` disabled.

Cities Skylines export now uses a temporary single joined mesh by default. Internal analysis still keeps body/wheel metadata, and the working blend is saved before the temporary export join.

Generated package:

- `build\rhino_tank_cs.fbx`
- `build\rhino_tank_cs_d.png`

The old strict command remains available only for isolated compatibility experiments:

```powershell
assetforge-export-fbx-strict .\rhino_tank.blend --json .\examples\rhino_tank_strict_export_report.json
```
