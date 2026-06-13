# Cities Skylines Import Test Checklist

Use this checklist for Release Candidate validation inside Cities Skylines Asset Editor.

- [ ] FBX loads
- [ ] Model orientation correct
- [ ] Scale correct
- [ ] Wheels detected
- [ ] Texture loads
- [ ] No missing materials
- [ ] Asset saves successfully

## Manual Steps

1. Open Cities Skylines.
2. Open `Tools > Asset Editor`.
3. Choose the appropriate vehicle template.
4. Import `build/<asset>_cs.fbx`.
5. Assign or confirm `build/<asset>_cs_d.png` as the diffuse texture if the editor does not auto-pick it.
6. Inspect orientation, scale, wheel placement, and material assignment.
7. Save the asset from Asset Editor.

## Current Automation Boundary

AssetForge can generate the FBX, diffuse texture, and build report, and can smoke-test FBX import through Blender. Final confirmation in Cities Skylines Asset Editor is still manual because the editor is an interactive Unity game tool and does not expose a reliable headless import API.
