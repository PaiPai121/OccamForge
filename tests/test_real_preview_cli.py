import subprocess
import sys


def test_real_preview_cli_help() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "assetforge.app.real_preview_cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Generate a real optimization preview" in completed.stdout
    assert "--target-triangles" in completed.stdout
