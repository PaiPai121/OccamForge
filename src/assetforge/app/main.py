from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from assetforge.app.composition import build_app_services
from assetforge.core.config import AssetForgeConfig
from assetforge.core.logging import configure_logging
from assetforge.gui.main_window import MainWindow


def main() -> int:
    config = AssetForgeConfig.from_environment()
    configure_logging(config.log_level, Path.cwd() / "logs")
    app = QApplication(sys.argv)
    app.setApplicationName("AssetForge")
    app.setOrganizationName("AssetForge")
    services = build_app_services(config)
    window = MainWindow(
        services.vehicle_analysis,
        services.vehicle_optimization,
        services.blender_configuration,
    )
    window.resize(820, 580)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
