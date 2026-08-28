from datetime import UTC, datetime, timedelta
from pathlib import Path

from click.testing import CliRunner
from sqlalchemy import func, inspect, select

from roleradar.analytics.skill_matcher import extract_and_persist_job_skills
from roleradar.app.cli import cli
from roleradar.ingestion.fetch_jobs import IngestionResult
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.models import (
    DuplicateAuditLog,
    DuplicateJobCandidate,
    Job,
    JobSkill,
    PostingObservation,
    SourceListing,
)
from roleradar.storage.repositories import JobRepository, SkillRepository


def test_cli_help_renders() -> None:
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "Singapore-focused job market intelligence" in result.output
    assert "config" in result.output
    assert "serve" in result.output


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
    assert "[adzuna|careers_gov|greenhouse|jobstreet|lever]" in result.output
    assert "--query" in result.output
    assert "--location" in result.output
    assert "--max-pages" in result.output
    assert "--role-family" in result.output


def test_adzuna_ingest_requires_query_and_location() -> None:
    result = CliRunner().invoke(cli, ["ingest", "--source", "adzuna"])

    assert result.exit_code != 0
    assert "Adzuna ingestion requires --query and --location" in result.output


def test_jobstreet_ingest_requires_query_and_location() -> None:
    result = CliRunner().invoke(cli, ["ingest", "--source", "jobstreet"])

    assert result.exit_code != 0
    assert "Jobstreet ingestion requires --query and --location" in result.output


def test_ingest_command_passes_role_family_to_ingestion(monkeypatch) -> None:
    calls = []

    def fake_ingest_jobs(**kwargs):
        calls.append(kwargs)
        return IngestionResult(
            source=kwargs["source"],
            targets_seen=1,
            targets_ingested=1,
            targets_failed=0,
            jobs_seen=1,
            source_listings_upserted=1,
            observations_created=1,
            job_skills_extracted=0,
            duplicate_candidates=0,
        )

    monkeypatch.setattr("roleradar.app.cli.ingest_jobs", fake_ingest_jobs)

    result = CliRunner().invoke(
        cli,
        [
            "ingest",
            "--source",
            "careers_gov",
            "--query",
            "data engineer",
            "--role-family",
            "data_engineer",
        ],
    )

    assert result.exit_code == 0
    assert calls[0]["role_family_id"] == "data_engineer"


def test_ingest_command_normalizes_custom_role_family(monkeypatch) -> None:
    calls = []

    def fake_ingest_jobs(**kwargs):
        calls.append(kwargs)
        return IngestionResult(
            source=kwargs["source"],
            targets_seen=1,
            targets_ingested=1,
            targets_failed=0,
            jobs_seen=1,
            source_listings_upserted=1,
            observations_created=1,
            job_skills_extracted=0,
            duplicate_candidates=0,
        )

    monkeypatch.setattr("roleradar.app.cli.ingest_jobs", fake_ingest_jobs)

    result = CliRunner().invoke(
        cli,
        [
            "ingest",
            "--source",
            "careers_gov",
            "--query",
            "data platform",
            "--role-family",
            "custom:Data Platform",
        ],
    )

    assert result.exit_code == 0
    assert calls[0]["role_family_id"] == "custom:data_platform"


def test_scheduled_ingest_active_targets_are_careers_gov_only() -> None:
    script = Path("scheduled_ingest.sh").read_text(encoding="utf-8")
    active_targets = [
        line.strip()
        for line in script.splitlines()
        if line.strip().startswith('"') and "|" in line
    ]

    assert active_targets
    assert all(line.startswith('"careers_gov|') for line in active_targets)
    assert '# "jobstreet|AI engineer' in script
    assert 'RETENTION_DAYS="${ROLERADAR_RETENTION_DAYS:-30}"' in script
    assert "prune-roles" in script


def test_prune_roles_dry_run_preserves_expired_closed_roles(tmp_path) -> None:
    db_path = tmp_path / "retention-dry-run.sqlite3"
    database_url = f"sqlite:///{db_path}"
    _seed_retention_database(database_url)

    result = CliRunner().invoke(
        cli,
        ["prune-roles", "--closed-for-days", "30", "--dry-run"],
        env={"ROLERADAR_DATABASE_URL": database_url},
    )

    assert result.exit_code == 0
    assert "jobs=1" in result.output
    assert "source_listings=1" in result.output
    assert "observations=1" in result.output
    assert "duplicate_candidates=1" in result.output
    assert "duplicate_audit_logs=1" in result.output
    assert "dry_run=true" in result.output
    assert _model_count(database_url, Job) == 3


def test_prune_roles_deletes_only_roles_closed_for_retention_period(tmp_path) -> None:
    db_path = tmp_path / "retention.sqlite3"
    database_url = f"sqlite:///{db_path}"
    _seed_retention_database(database_url)

    result = CliRunner().invoke(
        cli,
        ["prune-roles", "--closed-for-days", "30"],
        env={"ROLERADAR_DATABASE_URL": database_url},
    )

    assert result.exit_code == 0
    assert "jobs=1" in result.output
    assert "dry_run=false" in result.output
    assert _model_count(database_url, Job) == 2
    assert _model_count(database_url, SourceListing) == 2
    assert _model_count(database_url, PostingObservation) == 2
    assert _model_count(database_url, DuplicateJobCandidate) == 0
    assert _model_count(database_url, DuplicateAuditLog) == 0

    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        remaining_urls = set(session.scalars(select(Job.canonical_url)))
    assert remaining_urls == {
        "https://example.test/retention/recently-closed",
        "https://example.test/retention/active",
    }


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


def test_classify_skills_command_backfills_existing_jobs_and_is_idempotent(
    tmp_path,
) -> None:
    db_path = tmp_path / "classify.sqlite3"
    database_url = f"sqlite:///{db_path}"
    _seed_unclassified_skill_database(database_url)

    first_result = CliRunner().invoke(
        cli,
        ["classify-skills"],
        env={"ROLERADAR_DATABASE_URL": database_url},
    )
    second_result = CliRunner().invoke(
        cli,
        ["classify-skills"],
        env={"ROLERADAR_DATABASE_URL": database_url},
    )

    assert first_result.exit_code == 0
    assert "jobs_scanned=2" in first_result.output
    assert "jobs_with_matches=2" in first_result.output
    assert "total_matches=3" in first_result.output
    assert "newly_persisted_job_skills=3" in first_result.output
    assert "active_jobs_missing_skills=0" in first_result.output
    assert second_result.exit_code == 0
    assert "newly_persisted_job_skills=0" in second_result.output
    assert _job_skill_count(database_url) == 3


def test_classify_skills_dry_run_does_not_commit(tmp_path) -> None:
    db_path = tmp_path / "classify-dry-run.sqlite3"
    database_url = f"sqlite:///{db_path}"
    _seed_unclassified_skill_database(database_url)

    result = CliRunner().invoke(
        cli,
        ["classify-skills", "--dry-run"],
        env={"ROLERADAR_DATABASE_URL": database_url},
    )

    assert result.exit_code == 0
    assert "jobs_scanned=2" in result.output
    assert "total_matches=3" in result.output
    assert "newly_persisted_job_skills=0" in result.output
    assert "dry_run=true" in result.output
    assert _job_skill_count(database_url) == 0


def test_classify_skills_days_filters_active_jobs_last_seen_within_window(
    tmp_path,
) -> None:
    db_path = tmp_path / "classify-days.sqlite3"
    database_url = f"sqlite:///{db_path}"
    _seed_unclassified_skill_database(database_url, include_old_job=True)

    result = CliRunner().invoke(
        cli,
        ["classify-skills", "--days", "3"],
        env={"ROLERADAR_DATABASE_URL": database_url},
    )

    assert result.exit_code == 0
    assert "jobs_scanned=2" in result.output
    assert "total_matches=3" in result.output
    assert "newly_persisted_job_skills=3" in result.output
    assert _job_skill_count(database_url) == 3


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
    assert "Skill extraction coverage by source" in result.output
    assert "lever\t2\t2\t0\t2\t100%" in result.output
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
    assert "Salary coverage: 2/2 active postings (100%)" in result.output
    assert (
        "currency\tinterval\tpostings\tclosed_ranges\tmin\tmax\tavg_min\tavg_max"
        "\tavg_midpoint\tavg_annualized_midpoint" in result.output
    )
    assert "SGD\tmonthly\t2\t2\t6000\t9000\t6500\t8500\t7500\t90000" in result.output
    assert "Highest annualized salary listings" in result.output
    assert (
        "Example\tSoftware Engineer\tlever\tSGD\tmonthly\t7000\t9000\t96000"
        in result.output
    )
    assert "Annualized salary by skill" in result.output
    assert "Python\t2\t90000" in result.output


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


def _seed_retention_database(database_url: str) -> None:
    engine = create_database_engine(database_url)
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        job_repo = JobRepository(session)
        company = job_repo.get_or_create_company(name="Retention Example")
        expired_job = job_repo.get_or_create_job(
            title="Expired Role",
            company=company,
            canonical_url="https://example.test/retention/expired",
            description_text="Python",
        )
        recently_closed_job = job_repo.get_or_create_job(
            title="Recently Closed Role",
            company=company,
            canonical_url="https://example.test/retention/recently-closed",
            description_text="Python",
        )
        active_job = job_repo.get_or_create_job(
            title="Long-running Active Role",
            company=company,
            canonical_url="https://example.test/retention/active",
            description_text="Python",
        )
        now = datetime.now(UTC)
        active_job.first_seen_at = now - timedelta(days=90)

        for index, job in enumerate(
            (expired_job, recently_closed_job, active_job),
            start=1,
        ):
            listing = job_repo.upsert_source_listing(
                source="careers_gov",
                source_job_id=f"careers_gov:retention:{index}",
                job=job,
                description_text="Python",
            )
            job_repo.record_observation(source_listing=listing)

        expired_job.closed_at = now - timedelta(days=31)
        recently_closed_job.closed_at = now - timedelta(days=29)

        skill = SkillRepository(session).get_or_create_skill(name="Python")
        session.add(
            JobSkill(
                job=expired_job,
                skill=skill,
                extraction_method="test",
            )
        )
        session.flush()
        duplicate = DuplicateJobCandidate(
            job_id=expired_job.id,
            candidate_job_id=active_job.id,
            match_type="test",
            score=1.0,
            reason="retention dependency test",
        )
        session.add(duplicate)
        session.flush()
        session.add(
            DuplicateAuditLog(
                duplicate_candidate_id=duplicate.id,
                action="reviewed",
                new_status="reviewed",
            )
        )
        session.commit()


def _seed_unclassified_skill_database(
    database_url: str,
    *,
    include_old_job: bool = False,
) -> None:
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
            canonical_url="https://example.test/unclassified/1",
            description_text="Python and SQL",
        )
        second_job = job_repo.get_or_create_job(
            title="Software Engineer",
            company=company,
            canonical_url="https://example.test/unclassified/2",
            description_text="Python",
        )
        job_repo.upsert_source_listing(
            source="careers_gov",
            source_job_id="careers_gov:1",
            job=first_job,
        )
        job_repo.upsert_source_listing(
            source="careers_gov",
            source_job_id="careers_gov:2",
            job=second_job,
        )

        if include_old_job:
            old_job = job_repo.get_or_create_job(
                title="Legacy Data Analyst",
                company=company,
                canonical_url="https://example.test/unclassified/old",
                description_text="Python and SQL",
            )
            old_time = datetime.now(UTC) - timedelta(days=10)
            old_job.last_seen_at = old_time
            job_repo.upsert_source_listing(
                source="careers_gov",
                source_job_id="careers_gov:old",
                job=old_job,
            )

        session.commit()


def _job_skill_count(database_url: str) -> int:
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(JobSkill)) or 0)


def _model_count(database_url: str, model) -> int:
    engine = create_database_engine(database_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        return int(session.scalar(select(func.count()).select_from(model)) or 0)
