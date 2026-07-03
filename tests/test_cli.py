from click.testing import CliRunner
from sqlalchemy import inspect

from roleradar.analytics.skill_matcher import extract_and_persist_job_skills
from roleradar.app.cli import cli
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.repositories import JobRepository, SkillRepository


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
    assert "ssg_wsg_credentials_configured: False" in result.output


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


def test_ingest_help_lists_adzuna_source() -> None:
    result = CliRunner().invoke(cli, ["ingest", "--help"])

    assert result.exit_code == 0
    assert "[adzuna|careers_gov|greenhouse|lever]" in result.output
    assert "--query" in result.output
    assert "--location" in result.output
    assert "--max-pages" in result.output



def test_adzuna_ingest_requires_query_and_location() -> None:
    result = CliRunner().invoke(cli, ["ingest", "--source", "adzuna"])

    assert result.exit_code != 0
    assert "Adzuna ingestion requires --query and --location" in result.output



def test_sync_taxonomy_missing_credentials_skips(tmp_path) -> None:
    db_path = tmp_path / "taxonomy-sync.sqlite3"
    database_url = f"sqlite:///{db_path}"

    result = CliRunner().invoke(
        cli,
        ["sync-taxonomy", "--source", "ssg-wsg"],
        env={"ROLERADAR_DATABASE_URL": database_url},
    )

    assert result.exit_code == 0
    assert "skipped taxonomy sync: source=ssg-wsg" in result.output
    assert "ROLERADAR_SSG_WSG_CLIENT_ID" in result.output


def test_report_skills_command_renders_snapshot(tmp_path) -> None:
    db_path = tmp_path / "skills-report.sqlite3"
    database_url = f"sqlite:///{db_path}"
    _seed_report_database(database_url)

    result = CliRunner().invoke(
        cli,
        ["report", "skills", "--days", "30", "--limit", "5"],
        env={"ROLERADAR_DATABASE_URL": database_url},
    )

    assert result.exit_code == 0
    assert "Skill report: current snapshot" in result.output
    assert "Trend caveat: growth is not reported" in result.output
    assert "Top skills" in result.output
    assert "Python\t2" in result.output
    assert "Skills by source" in result.output
    assert "lever\tSQL\t1" in result.output
    assert "Skills by company" in result.output
    assert "Example\tPython\t2" in result.output
    assert "Skills by role/title keyword" in result.output
    assert "data\tSQL\t1" in result.output


def test_report_salaries_command_renders_snapshot(tmp_path) -> None:
    db_path = tmp_path / "salary-report.sqlite3"
    database_url = f"sqlite:///{db_path}"
    _seed_report_database(database_url)

    result = CliRunner().invoke(
        cli,
        ["report", "salaries", "--days", "30"],
        env={"ROLERADAR_DATABASE_URL": database_url},
    )

    assert result.exit_code == 0
    assert "Salary report: current snapshot" in result.output
    assert (
        "currency\tinterval\tpostings\tmin\tmax\tavg_min\tavg_max\tavg_midpoint"
        in result.output
    )
    assert "SGD\tmonthly\t2\t6000\t9000\t6500\t8500\t7500" in result.output


def _seed_report_database(database_url: str) -> None:
    engine = create_database_engine(database_url)
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        skill_repo = SkillRepository(session)
        python = skill_repo.get_or_create_skill(name="Python")
        sql = skill_repo.get_or_create_skill(name="SQL")
        skill_repo.get_or_create_alias(skill=python, alias="Python")
        skill_repo.get_or_create_alias(skill=sql, alias="SQL")

        job_repo = JobRepository(session)
        company = job_repo.get_or_create_company(name="Example")
        first_job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=company,
            canonical_url="https://example.test/jobs/1",
            description_text="Python and SQL",
        )
        second_job = job_repo.get_or_create_job(
            title="Software Engineer",
            company=company,
            canonical_url="https://example.test/jobs/2",
            description_text="Python",
        )
        job_repo.upsert_source_listing(
            source="lever",
            source_job_id="lever:1",
            job=first_job,
            salary_min=6000,
            salary_max=8000,
            salary_currency="SGD",
            salary_interval="monthly",
        )
        job_repo.upsert_source_listing(
            source="lever",
            source_job_id="lever:2",
            job=second_job,
            salary_min=7000,
            salary_max=9000,
            salary_currency="SGD",
            salary_interval="monthly",
        )
        extract_and_persist_job_skills(session, first_job)
        extract_and_persist_job_skills(session, second_job)
        session.commit()
