import subprocess
import sys


def test_qem_heatmap_cli_help() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "assetforge.app.qem_heatmap_cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Generate a QEM edge collapse cost heatmap" in completed.stdout
    assert "--output" in completed.stdout
