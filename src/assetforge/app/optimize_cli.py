from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from assetforge.app.composition import build_app_services
from assetforge.core.config import AssetForgeConfig
from assetforge.core.logging import configure_logging
from assetforge.models.optimization_dto import optimization_report_to_dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize a Blender vehicle asset.")
    parser.add_argument("blend_file", type=Path)
    parser.add_argument("--profile", default="generic_vehicle")
    parser.add_argument("--target-triangles", type=int, default=None)
    parser.add_argument("--json", type=Path, help="Optional path for report JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = AssetForgeConfig.from_environment()
    configure_logging(config.log_level)
    services = build_app_services(config)
    try:
        report = services.vehicle_optimization.optimize_vehicle(
            args.blend_file,
            args.profile,
            args.target_triangles,
        )
    except Exception as exc:  # noqa: BLE001 - CLI should present clean operational errors.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = optimization_report_to_dict(report)
    text = json.dumps(payload, indent=2)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report.is_successful else 1


if __name__ == "__main__":
    raise SystemExit(main())

