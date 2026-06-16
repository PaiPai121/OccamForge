from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from assetforge.app.composition import build_app_services
from assetforge.core.config import AssetForgeConfig
from assetforge.core.logging import configure_logging
from assetforge.models.simplification_report_dto import simplification_report_to_dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a simplification diff report.")
    parser.add_argument("source_blend_file", type=Path)
    parser.add_argument(
        "--optimized-blend",
        type=Path,
        help="Optimized .blend to compare. Defaults to <source>_optimized.blend.",
    )
    parser.add_argument("--output", type=Path, default=Path("simplification_reports"))
    parser.add_argument("--json", type=Path, help="Optional path for report JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = AssetForgeConfig.from_environment()
    configure_logging(config.log_level)
    services = build_app_services(config)
    try:
        report = services.simplification_report.generate(
            args.source_blend_file,
            args.optimized_blend,
            args.output,
        )
    except Exception as exc:  # noqa: BLE001 - CLI should present clean operational errors.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = simplification_report_to_dict(report)
    text = json.dumps(payload, indent=2)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report.is_successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
