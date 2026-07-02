"""Command-line interface for RoleRadar."""

from __future__ import annotations

import click

from roleradar import __version__
from roleradar.config.settings import Settings
from roleradar.storage.database import init_database


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=__version__, prog_name="roleradar")
def cli() -> None:
    """Singapore-focused job market intelligence tooling."""


@cli.command("config")
def show_config() -> None:
    """Show non-secret runtime configuration."""
    settings = Settings()
    click.echo(f"environment: {settings.environment}")
    click.echo(f"database_url: {settings.database_url}")
    click.echo(f"log_level: {settings.log_level}")
    click.echo(f"sqlite_wal: {settings.sqlite_wal}")
    click.echo(f"sqlite_busy_timeout_ms: {settings.sqlite_busy_timeout_ms}")


@cli.command("init-db")
def init_db() -> None:
    """Create database tables if they do not already exist."""
    settings = Settings()
    init_database(settings)
    click.echo(f"initialized database: {settings.database_url}")


def main() -> None:
    """Run the RoleRadar CLI."""
    cli()


if __name__ == "__main__":
    main()
