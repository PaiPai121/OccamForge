from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from assetforge.app.composition import build_app_services
from assetforge.core.config import AssetForgeConfig
from assetforge.core.logging import configure_logging
from assetforge.models.geometry_report_dto import geometry_report_to_dict


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a geometry density report.")
    parser.add_argument("source_file", type=Path)
    parser.add_argument("--output", type=Path, default=Path("geometry_reports"))
    parser.add_argument("--json", type=Path, help="Optional path for report JSON output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = AssetForgeConfig.from_environment()
    configure_logging(config.log_level)
    services = build_app_services(config)
    try:
        report = services.geometry_report.generate(args.source_file, args.output)
    except Exception as exc:  # noqa: BLE001 - CLI should present clean operational errors.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = geometry_report_to_dict(report)
    text = json.dumps(payload, indent=2)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report.is_successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
