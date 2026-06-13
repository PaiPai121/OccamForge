# AssetForge Architecture

## Layers

- `domain`: pure dataclasses and rules. No Qt, no Blender.
- `services`: application use cases and interfaces.
- `blender`: infrastructure adapter that launches Blender and parses script output.
- `gui`: PySide6 presentation layer. It uses services only.
- `app`: composition root and process entry points.
- `models`: DTO mapping between external JSON and domain objects.

## Dependency Rule

Higher-level policy does not depend on infrastructure details:

```text
GUI -> services -> domain
CLI -> services -> domain
blender adapter -> services port + domain DTO mapping
```

The GUI must not import `bpy`, Blender scripts, or subprocess execution classes directly.

## Blender Execution

Blender operations run as:

```text
blender.exe --background --python analyze_vehicle.py -- --blend-file file.blend --output-json report.json
```

The script writes structured JSON. Validation failures such as missing `VehicleBody` are returned in `errors` rather than treated as process crashes.

## Blender Discovery

Blender discovery is isolated in `assetforge.blender.locator`. Search order:

1. Saved user configuration
2. Current-user and common Windows Start Menu shortcuts containing `blender`
3. `PATH`
4. Windows Registry uninstall entries
5. Steam libraries from `libraryfolders.vdf`
6. Manual Browse dialog through `BlenderConfigurationService`

Every candidate is validated with `blender.exe --version` before it is saved. The locator does not scan arbitrary drives, keeping normal startup responsive.

## Extension Points

Future operations belong behind explicit service ports:

- optimize vehicle
- bake textures
- generate LODs
- export FBX
- export Cities Skylines package
- export Transport Fever package
- batch processing

Export targets should be implemented as pluggable adapters with a common export interface.
