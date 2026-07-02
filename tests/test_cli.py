from click.testing import CliRunner
from sqlalchemy import inspect

from roleradar.app.cli import cli
from roleradar.storage.database import create_database_engine


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


def test_init_db_command_creates_database(tmp_path) -> None:
    db_path = tmp_path / "cli.sqlite3"
    database_url = f"sqlite:///{db_path}"

    result = CliRunner().invoke(
        cli,
        ["init-db"],
        env={"ROLERADAR_DATABASE_URL": database_url},
    )

    assert result.exit_code == 0
    assert f"initialized database: {database_url}" in result.output

    engine = create_database_engine(database_url)
    assert "ingestion_runs" in inspect(engine).get_table_names()
