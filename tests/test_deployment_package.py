from pathlib import Path


def test_deployment_package_files_exist():
    base = Path("deployment_package")
    assert (base / "README.md").exists()
    assert (base / "default_config.json").exists()
    assert (base / "run_cli.bat").exists()
    assert (base / "requirements.txt").exists()
