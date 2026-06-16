import subprocess
import sys


def test_geometry_report_cli_help() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "assetforge.app.geometry_report_cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Generate a geometry density report" in completed.stdout
    assert "--output" in completed.stdout
