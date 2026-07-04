from datetime import UTC, datetime, timedelta

from roleradar.analytics.skill_matcher import extract_and_persist_job_skills
from roleradar.analytics.trend_engine import (
    company_hiring_velocity,
    posting_velocity,
    salary_trend_over_time,
    skill_demand_over_time,
    time_to_close,
)
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.repositories import JobRepository, SkillRepository

AS_OF = datetime(2026, 7, 4, tzinfo=UTC)
THIS_WEEK = datetime(2026, 6, 29, 9, tzinfo=UTC)
LAST_WEEK = THIS_WEEK - timedelta(weeks=1)


def test_skill_demand_over_time_counts_active_jobs_by_week(tmp_path) -> None:
    session_factory = _session_factory(tmp_path, "skill-demand.sqlite3")

    with session_factory() as session:
        skill_repo = SkillRepository(session)
        python = skill_repo.get_or_create_skill(name="Python")
        skill_repo.get_or_create_alias(skill=python, alias="Python")

        job_repo = JobRepository(session)
        company = job_repo.get_or_create_company(name="Example")
        first_job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=company,
            canonical_url="https://example.test/jobs/1",
            description_text="Python",
        )
        second_job = job_repo.get_or_create_job(
            title="Analytics Engineer",
            company=company,
            canonical_url="https://example.test/jobs/2",
            description_text="Python",
        )
        first_listing = job_repo.upsert_source_listing(
            source="lever",
            source_job_id="lever:1",
            job=first_job,
        )
        second_listing = job_repo.upsert_source_listing(
            source="lever",
            source_job_id="lever:2",
            job=second_job,
        )
        extract_and_persist_job_skills(session, first_job)
        extract_and_persist_job_skills(session, second_job)

        first_observation = job_repo.record_observation(source_listing=first_listing)
        first_observation.observed_at = LAST_WEEK
        second_observation = job_repo.record_observation(source_listing=second_listing)
        second_observation.observed_at = THIS_WEEK
        session.commit()

        rows = skill_demand_over_time(
            session,
            skill_name="Python",
            weeks=2,
            as_of=AS_OF,
        )

    assert [row.week_start for row in rows] == [LAST_WEEK.date(), THIS_WEEK.date()]
    assert [row.count for row in rows] == [1, 1]
    assert rows[1].previous_count == 1
    assert rows[1].delta == 0
    assert rows[1].delta_percent == 0


def test_salary_trend_over_time_averages_salary_midpoints_for_family(tmp_path) -> None:
    session_factory = _session_factory(tmp_path, "salary-trend.sqlite3")

    with session_factory() as session:
        job_repo = JobRepository(session)
        company = job_repo.get_or_create_company(name="Example")
        data_job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=company,
            canonical_url="https://example.test/jobs/data",
            role_family_id="data",
        )
        software_job = job_repo.get_or_create_job(
            title="Software Engineer",
            company=company,
            canonical_url="https://example.test/jobs/software",
            role_family_id="software",
        )
        data_listing = job_repo.upsert_source_listing(
            source="lever",
            source_job_id="lever:data",
            job=data_job,
            salary_min=6000,
            salary_max=8000,
            salary_interval="monthly",
        )
        software_listing = job_repo.upsert_source_listing(
            source="lever",
            source_job_id="lever:software",
            job=software_job,
            salary_min=10000,
            salary_max=12000,
            salary_interval="monthly",
        )
        data_observation = job_repo.record_observation(source_listing=data_listing)
        data_observation.observed_at = THIS_WEEK
        software_observation = job_repo.record_observation(
            source_listing=software_listing
        )
        software_observation.observed_at = THIS_WEEK
        session.commit()

        rows = salary_trend_over_time(
            session,
            family_id="data",
            weeks=2,
            as_of=AS_OF,
        )

    assert rows[0].posting_count == 0
    assert rows[0].average_annualized_midpoint is None
    assert rows[1].posting_count == 1
    assert rows[1].average_annualized_midpoint == 84000


def test_posting_velocity_and_company_hiring_velocity_use_first_seen(tmp_path) -> None:
    session_factory = _session_factory(tmp_path, "velocity.sqlite3")

    with session_factory() as session:
        job_repo = JobRepository(session)
        alpha = job_repo.get_or_create_company(name="Alpha")
        beta = job_repo.get_or_create_company(name="Beta")
        alpha_job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=alpha,
            canonical_url="https://example.test/jobs/alpha",
            role_family_id="data",
        )
        beta_job = job_repo.get_or_create_job(
            title="Data Engineer",
            company=beta,
            canonical_url="https://example.test/jobs/beta",
            role_family_id="data",
        )
        old_job = job_repo.get_or_create_job(
            title="Software Engineer",
            company=alpha,
            canonical_url="https://example.test/jobs/old",
            role_family_id="software",
        )
        alpha_job.first_seen_at = LAST_WEEK
        beta_job.first_seen_at = THIS_WEEK
        beta_job.closed_at = THIS_WEEK + timedelta(days=2)
        old_job.first_seen_at = LAST_WEEK
        session.commit()

        velocity = posting_velocity(
            session,
            family_id="data",
            weeks=2,
            as_of=AS_OF,
        )
        company_velocity = company_hiring_velocity(
            session,
            family_id="data",
            weeks=2,
            as_of=AS_OF,
        )

    assert [(row.new_posting_count, row.closed_posting_count) for row in velocity] == [
        (1, 0),
        (1, 1),
    ]
    assert ("Alpha", LAST_WEEK.date(), 1) in [
        (row.company_name, row.week_start, row.new_posting_count)
        for row in company_velocity
    ]
    assert ("Beta", THIS_WEEK.date(), 1) in [
        (row.company_name, row.week_start, row.new_posting_count)
        for row in company_velocity
    ]


def test_time_to_close_returns_median_and_p75_for_closed_jobs(tmp_path) -> None:
    session_factory = _session_factory(tmp_path, "time-to-close.sqlite3")

    with session_factory() as session:
        job_repo = JobRepository(session)
        company = job_repo.get_or_create_company(name="Example")
        durations = [7, 14, 28, 42]
        for duration in durations:
            job = job_repo.get_or_create_job(
                title=f"Data Analyst {duration}",
                company=company,
                canonical_url=f"https://example.test/jobs/{duration}",
                role_family_id="data",
            )
            job.first_seen_at = THIS_WEEK
            job.closed_at = THIS_WEEK + timedelta(days=duration)
        session.commit()

        stats = time_to_close(session, family_id="data")

    assert stats.posting_count == 4
    assert stats.median_days == 21
    assert stats.p75_days == 31.5


def _session_factory(tmp_path, filename: str):
    engine = create_database_engine(f"sqlite:///{tmp_path / filename}")
    init_database(engine=engine)
    return create_session_factory(engine)
