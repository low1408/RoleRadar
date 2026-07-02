from click.testing import CliRunner

from roleradar.app.cli import cli


def test_cli_help_renders() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "Singapore-focused job market intelligence" in result.output
    assert "config" in result.output


def test_config_command_renders_defaults() -> None:
    result = CliRunner().invoke(cli, ["config"])

    assert result.exit_code == 0
    assert "environment: development" in result.output
    assert "sqlite_wal: True" in result.output

