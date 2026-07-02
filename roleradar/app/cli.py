"""Command-line interface for RoleRadar."""

from __future__ import annotations

import click

from roleradar import __version__
from roleradar.config.settings import Settings
from roleradar.analytics.skill_trends import top_skills
from roleradar.ingestion.fetch_jobs import ingest_jobs
from roleradar.sources.seed_loader import load_taxonomy_seed
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)


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


@cli.command("seed-taxonomy")
@click.option(
    "--file",
    "file_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=str),
    help="Path to a taxonomy CSV or XLSX seed file.",
)
def seed_taxonomy(file_path: str) -> None:
    """Load local skill taxonomy seed data."""
    settings = Settings()
    engine = create_database_engine(
        settings.database_url,
        sqlite_wal=settings.sqlite_wal,
        sqlite_busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        result = load_taxonomy_seed(session, file_path)
        session.commit()

    click.echo(
        "seeded taxonomy: "
        f"rows={result.rows_read} "
        f"skills={result.skills_seen} "
        f"aliases={result.aliases_seen}"
    )


@cli.command("ingest")
@click.option(
    "--source",
    required=True,
    type=click.Choice(["lever"]),
    help="Source to ingest. Phase 3 supports Lever.",
)
@click.option(
    "--targets",
    "targets_file",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=str),
    help="CSV file containing target companies.",
)
def ingest(source: str, targets_file: str) -> None:
    """Ingest jobs from a configured source."""
    settings = Settings()
    result = ingest_jobs(
        database_url=settings.database_url,
        source=source,
        targets_file=targets_file,
        sqlite_wal=settings.sqlite_wal,
        sqlite_busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
    click.echo(
        "ingested jobs: "
        f"source={result.source} "
        f"targets={result.targets_ingested}/{result.targets_seen} "
        f"jobs={result.jobs_seen} "
        f"listings={result.source_listings_upserted} "
        f"observations={result.observations_created} "
        f"job_skills={result.job_skills_extracted}"
    )


@cli.group("report")
def report() -> None:
    """Run local analytics reports."""


@report.command("skills")
@click.option("--limit", default=10, show_default=True, type=click.IntRange(min=1))
def report_skills(limit: int) -> None:
    """Show top skills in active postings."""
    settings = Settings()
    engine = create_database_engine(
        settings.database_url,
        sqlite_wal=settings.sqlite_wal,
        sqlite_busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        rows = top_skills(session, limit=limit)

    if not rows:
        click.echo("No skill data found.")
        return

    for row in rows:
        click.echo(f"{row.skill_name}\t{row.job_count}")


def main() -> None:
    """Run the RoleRadar CLI."""
    cli()


if __name__ == "__main__":
    main()
