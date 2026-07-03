"""Command-line interface for RoleRadar."""

from __future__ import annotations

import click

from roleradar import __version__
from roleradar.analytics.salary_trends import salary_range_summaries
from roleradar.analytics.skill_trends import (
    skills_by_company,
    skills_by_role_keyword,
    skills_by_source,
    top_skills,
)
from roleradar.config.settings import Settings
from roleradar.ingestion.fetch_jobs import ingest_jobs
from roleradar.sources.seed_loader import load_taxonomy_seed
from roleradar.sources.ssg_wsg import sync_taxonomy_from_ssg_wsg
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
    click.echo(f"careers_gov_timeout_seconds: {settings.careers_gov_timeout_seconds}")
    click.echo(f"careers_gov_throttle_seconds: {settings.careers_gov_throttle_seconds}")
    click.echo(f"ssg_wsg_taxonomy_url: {settings.ssg_wsg_taxonomy_url}")
    click.echo(f"ssg_wsg_timeout_seconds: {settings.ssg_wsg_timeout_seconds}")
    click.echo(
        "ssg_wsg_credentials_configured: "
        f"{bool(settings.ssg_wsg_client_id and settings.ssg_wsg_client_secret)}"
    )


@cli.command("init-db")
def init_db() -> None:
    """Create database tables that do not already exist."""
    settings = Settings()
    init_database(settings)
    click.echo(f"initialized database: {settings.database_url}")


@cli.command("seed-taxonomy")
@click.option(
    "--file",
    "file_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=str),
    help="Path to taxonomy CSV or XLSX seed file.",
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


@cli.command("sync-taxonomy")
@click.option(
    "--source",
    required=True,
    type=click.Choice(["ssg-wsg"]),
    help="Source taxonomy sync.",
)
def sync_taxonomy(source: str) -> None:
    """Sync live skill taxonomy data from an official source."""
    settings = Settings()
    engine = create_database_engine(
        settings.database_url,
        sqlite_wal=settings.sqlite_wal,
        sqlite_busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        if source == "ssg-wsg":
            result = sync_taxonomy_from_ssg_wsg(
                session,
                client_id=settings.ssg_wsg_client_id,
                client_secret=settings.ssg_wsg_client_secret,
                taxonomy_url=settings.ssg_wsg_taxonomy_url,
                timeout_seconds=settings.ssg_wsg_timeout_seconds,
            )
        else:
            raise click.UsageError(f"Unsupported taxonomy sync source: {source}")

        if result.status == "completed":
            session.commit()
        else:
            session.rollback()

    if result.status == "skipped":
        click.echo(
            f"skipped taxonomy sync: source={result.source} reason={result.message}"
        )
        return

    source_updated_at = (
        result.source_updated_at.isoformat() if result.source_updated_at else "unknown"
    )
    click.echo(
        "synced taxonomy: "
        f"source={result.source} "
        f"status={result.status} "
        f"skills={result.skills_seen} "
        f"aliases={result.aliases_seen} "
        f"version={result.taxonomy_version or 'unknown'} "
        f"source_updated_at={source_updated_at}"
    )


@cli.command("ingest")
@click.option(
    "--source",
    required=True,
    type=click.Choice(["adzuna", "careers_gov", "greenhouse", "lever"]),
    help="Source to ingest.",
)
@click.option(
    "--targets",
    "targets_file",
    required=False,
    type=click.Path(exists=True, dir_okay=False, path_type=str),
    help="CSV file containing target companies for board-based sources.",
)
@click.option("--query", help="Search query for API-based ingestion.")
@click.option("--location", help="Location filter for Adzuna ingestion.")
@click.option("--country", default="sg", show_default=True, help="Adzuna country code.")
@click.option(
    "--results-per-page",
    default=20,
    show_default=True,
    type=click.IntRange(min=1, max=100),
    help="API results per page.",
)
@click.option(
    "--max-pages",
    default=1,
    show_default=True,
    type=click.IntRange(min=1),
    help="Maximum API pages to fetch.",
)
def ingest(
    source: str,
    targets_file: str | None,
    query: str | None,
    location: str | None,
    country: str,
    results_per_page: int,
    max_pages: int,
) -> None:
    """Ingest jobs from a configured source."""
    settings = Settings()
    if source == "adzuna":
        if not query or not location:
            raise click.UsageError("Adzuna ingestion requires --query and --location.")
    elif source == "careers_gov":
        pass
    elif targets_file is None:
        raise click.UsageError(f"{source} ingestion requires --targets.")

    result = ingest_jobs(
        database_url=settings.database_url,
        source=source,
        targets_file=targets_file,
        query=query,
        location=location,
        country=country,
        results_per_page=results_per_page,
        max_pages=max_pages,
        adzuna_app_id=settings.adzuna_app_id,
        adzuna_app_key=settings.adzuna_app_key,
        careers_gov_timeout_seconds=settings.careers_gov_timeout_seconds,
        careers_gov_throttle_seconds=settings.careers_gov_throttle_seconds,
        sqlite_wal=settings.sqlite_wal,
        sqlite_busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
    click.echo(
        "ingested jobs: "
        f"source={result.source} "
        f"targets={result.targets_ingested}/{result.targets_seen} "
        f"failed_targets={result.targets_failed} "
        f"jobs={result.jobs_seen} "
        f"source_listings={result.source_listings_upserted} "
        f"observations={result.observations_created} "
        f"job_skills={result.job_skills_extracted} "
        f"duplicate_candidates={result.duplicate_candidates}"
    )


@cli.group("report")
def report() -> None:
    """Render local analytics reports."""


@report.command("skills")
@click.option("--days", default=30, show_default=True, type=click.IntRange(min=1))
@click.option("--limit", default=10, show_default=True, type=click.IntRange(min=1))
def report_skills(days: int, limit: int) -> None:
    """Show current-snapshot skill metrics for active postings."""
    with _session_from_settings() as session:
        top_rows = top_skills(session, days=days, limit=limit)
        source_rows = skills_by_source(session, days=days, limit=limit)
        company_rows = skills_by_company(session, days=days, limit=limit)
        role_rows = skills_by_role_keyword(session, days=days)

    click.echo(
        f"Skill report: current snapshot, active postings seen in last {days} days"
    )
    click.echo("Trend caveat: growth is not reported until repeated windows exist.")
    click.echo("")
    _echo_skill_counts("Top skills", top_rows)
    _echo_source_counts("Skills by source", source_rows)
    _echo_company_counts("Skills by company", company_rows)
    _echo_role_counts("Skills by role/title keyword", role_rows)


@report.command("salaries")
@click.option("--days", default=30, show_default=True, type=click.IntRange(min=1))
def report_salaries(days: int) -> None:
    """Show current-snapshot employer-provided salary summaries."""
    with _session_from_settings() as session:
        summaries = salary_range_summaries(session, days=days)

    click.echo(
        f"Salary report: current snapshot, active postings seen in last {days} days"
    )
    click.echo("Trend caveat: growth is not reported until repeated windows exist.")
    click.echo("")

    if not summaries:
        click.echo("No employer-provided salary data found.")
        return

    click.echo("Salary ranges")
    click.echo("currency\tinterval\tpostings\tmin\tmax\tavg_min\tavg_max\tavg_midpoint")
    for summary in summaries:
        click.echo(
            "\t".join(
                [
                    summary.currency,
                    summary.interval,
                    str(summary.posting_count),
                    _format_number(summary.min_salary),
                    _format_number(summary.max_salary),
                    _format_number(summary.average_min_salary),
                    _format_number(summary.average_max_salary),
                    _format_number(summary.average_midpoint),
                ]
            )
        )


def _session_from_settings():
    settings = Settings()
    engine = create_database_engine(
        settings.database_url,
        sqlite_wal=settings.sqlite_wal,
        sqlite_busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
    init_database(engine=engine)
    session_factory = create_session_factory(engine)
    return session_factory()


def _echo_skill_counts(title: str, rows: list[object]) -> None:
    click.echo(title)
    if not rows:
        click.echo("No skill data found.")
        click.echo("")
        return

    click.echo("skill\tactive_jobs")
    for row in rows:
        click.echo(f"{row.skill_name}\t{row.job_count}")
    click.echo("")


def _echo_source_counts(title: str, rows: list[object]) -> None:
    click.echo(title)
    if not rows:
        click.echo("No skill data found.")
        click.echo("")
        return

    click.echo("source\tskill\tactive_postings")
    for row in rows:
        click.echo(f"{row.source}\t{row.skill_name}\t{row.posting_count}")
    click.echo("")


def _echo_company_counts(title: str, rows: list[object]) -> None:
    click.echo(title)
    if not rows:
        click.echo("No skill data found.")
        click.echo("")
        return

    click.echo("company\tskill\tactive_jobs")
    for row in rows:
        click.echo(f"{row.company_name}\t{row.skill_name}\t{row.job_count}")
    click.echo("")


def _echo_role_counts(title: str, rows: list[object]) -> None:
    click.echo(title)
    if not rows:
        click.echo("No skill data found.")
        click.echo("")
        return

    click.echo("role_keyword\tskill\tactive_jobs")
    for row in rows:
        click.echo(f"{row.role_keyword}\t{row.skill_name}\t{row.job_count}")
    click.echo("")


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}"


def main() -> None:
    """Run the RoleRadar CLI."""
    cli()


if __name__ == "__main__":
    main()
