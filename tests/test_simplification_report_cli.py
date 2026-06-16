import subprocess
import sys


def test_simplification_report_cli_help() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "assetforge.app.simplification_report_cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Generate a simplification diff report" in completed.stdout
    assert "--optimized-blend" in completed.stdout
