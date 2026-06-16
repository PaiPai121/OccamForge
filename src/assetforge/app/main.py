from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from assetforge.app.composition import build_app_services
from assetforge.core.config import AssetForgeConfig
from assetforge.core.logging import configure_logging
from assetforge.gui.web_main_window import WebMainWindow


def main() -> int:
    config = AssetForgeConfig.from_environment()
    configure_logging(config.log_level, Path.cwd() / "logs")
    app = QApplication(sys.argv)
    app.setApplicationName("OccamForge")
    app.setOrganizationName("OccamForge")
    services = build_app_services(config)
    window = WebMainWindow(
        services.vehicle_analysis,
        services.vehicle_validation,
        services.cities_skylines_build,
        services.preprocess,
        services.real_optimization_preview,
        services.model_preview,
        services.geometry_report,
        services.simplification_report,
        services.blender_configuration,
    )
    window.resize(1280, 860)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
