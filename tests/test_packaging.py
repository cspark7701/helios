"""Tests for package installation, imports, and CLI basics."""

import helios
from helios.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


def test_package_metadata():
    """Verify package version and author metadata."""
    assert hasattr(helios, "__version__")
    assert helios.__version__ == "0.1.0"
    assert hasattr(helios, "__author__")


def test_cli_version():
    """Verify CLI version command outputs expected text."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_cli_info():
    """Verify CLI info command outputs reference framework."""
    result = runner.invoke(app, ["info"])
    assert result.exit_code == 0
    assert "LBNL Osprey" in result.stdout
    assert "Heavy Ion" in result.stdout
