from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from assetforge.blender.executor import BlenderBackgroundExecutor
from assetforge.blender.locator import BlenderLocator
from assetforge.core.config import AssetForgeConfig, UserConfigStore
from assetforge.core.logging import configure_logging


SUPPORTED_QEM_HEATMAP_EXTENSIONS = {".blend", ".obj", ".fbx", ".glb", ".gltf"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a QEM edge collapse cost heatmap.")
    parser.add_argument("source_file", type=Path)
    parser.add_argument("--output", type=Path, default=Path("qem_heatmap"))
    parser.add_argument("--json", type=Path, help="Optional path for report JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = AssetForgeConfig.from_environment()
    configure_logging(config.log_level)
    source_file = args.source_file
    if not source_file.exists():
        print(f"ERROR: Model file does not exist: {source_file}", file=sys.stderr)
        return 2
    if source_file.suffix.lower() not in SUPPORTED_QEM_HEATMAP_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_QEM_HEATMAP_EXTENSIONS))
        print(f"ERROR: Expected one of {supported}, got: {source_file}", file=sys.stderr)
        return 2

    output_directory = args.output
    output_directory.mkdir(parents=True, exist_ok=True)
    report_path = args.json or output_directory / "qem_heatmap_report.json"
    script_path = (
        Path(__file__).parents[1]
        / "blender"
        / "scripts"
        / "generate_qem_heatmap.py"
    )
    executor = BlenderBackgroundExecutor(
        config,
        BlenderLocator(UserConfigStore(config.user_config_path), explicit_executable=config.blender_executable),
    )
    try:
        payload = executor.run_script(
            script_path,
            [
                "--source-file",
                str(source_file),
                "--output-directory",
                str(output_directory),
            ],
        )
    except Exception as exc:  # noqa: BLE001 - CLI should present clean operational errors.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    text = json.dumps(payload, indent=2)
    report_path.write_text(text, encoding="utf-8")
    print(text)
    return 0 if not payload.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
