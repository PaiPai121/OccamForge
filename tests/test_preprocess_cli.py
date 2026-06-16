import subprocess
import sys


def test_preprocess_cli_help() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "assetforge.app.preprocess_cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "Run safe Limited Dissolve preprocess" in completed.stdout
    assert "--angle-degrees" in completed.stdout
