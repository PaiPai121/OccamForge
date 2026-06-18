import subprocess
import sys


def test_scale_analysis_cli_help() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "assetforge.app.scale_analysis_cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Generate Scale Analysis V0 heatmaps" in completed.stdout
    assert "--object-name" in completed.stdout
    assert "--scales" in completed.stdout
