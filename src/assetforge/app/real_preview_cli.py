from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from assetforge.app.composition import build_app_services
from assetforge.core.config import AssetForgeConfig
from assetforge.core.logging import configure_logging
from assetforge.models.real_optimization_preview_dto import real_preview_report_to_dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a real optimization preview.")
    parser.add_argument("blend_file", type=Path)
    parser.add_argument(
        "--target-triangles",
        type=int,
        required=True,
        help="Maximum triangle count to preview.",
    )
    parser.add_argument("--output", type=Path, default=Path("previews"))
    parser.add_argument("--profile", default="cities_skylines_vehicle")
    parser.add_argument("--json", type=Path, help="Optional path for report JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = AssetForgeConfig.from_environment()
    configure_logging(config.log_level)
    services = build_app_services(config)
    try:
        report = services.real_optimization_preview.generate(
            args.blend_file,
            args.profile,
            args.target_triangles,
            args.output,
        )
    except Exception as exc:  # noqa: BLE001 - CLI should present clean operational errors.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = real_preview_report_to_dict(report)
    text = json.dumps(payload, indent=2)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report.is_successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
