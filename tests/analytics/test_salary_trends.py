from roleradar.analytics.salary_trends import (
    salary_coverage,
    salary_range_summaries,
    top_salary_listings,
)
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.repositories import JobRepository


def test_salary_range_summaries_group_employer_provided_ranges(tmp_path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'salary.sqlite3'}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        job_repo = JobRepository(session)
        company = job_repo.get_or_create_company(name="Example")
        first_job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=company,
            canonical_url="https://example.test/jobs/1",
        )
        second_job = job_repo.get_or_create_job(
            title="Analytics Engineer",
            company=company,
            canonical_url="https://example.test/jobs/2",
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
        session.commit()

        summaries = salary_range_summaries(session, days=30)

        assert len(summaries) == 1
        assert summaries[0].currency == "SGD"
        assert summaries[0].interval == "monthly"
        assert summaries[0].posting_count == 2
        assert summaries[0].closed_range_count == 2
        assert summaries[0].min_salary == 6000
        assert summaries[0].max_salary == 9000
        assert summaries[0].average_annualized_midpoint == 90000
        assert summaries[0].p25_annualized_midpoint == 87000
        assert summaries[0].median_annualized_midpoint == 90000
        assert summaries[0].p75_annualized_midpoint == 93000


def test_salary_range_summaries_do_not_treat_open_bounds_as_midpoints(
    tmp_path,
) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'open-bounds.sqlite3'}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        job_repo = JobRepository(session)
        company = job_repo.get_or_create_company(name="Example")
        job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=company,
            canonical_url="https://example.test/jobs/open",
        )
        job_repo.upsert_source_listing(
            source="lever",
            source_job_id="lever:open",
            job=job,
            salary_min=8000,
            salary_currency="SGD",
            salary_interval="monthly",
        )
        session.commit()

        summaries = salary_range_summaries(session, days=30)

        assert summaries[0].posting_count == 1
        assert summaries[0].closed_range_count == 0
        assert summaries[0].average_midpoint is None
        assert summaries[0].average_annualized_midpoint is None


def test_salary_coverage_counts_active_postings_without_salary(tmp_path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'coverage.sqlite3'}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        job_repo = JobRepository(session)
        company = job_repo.get_or_create_company(name="Example")
        paid_job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=company,
            canonical_url="https://example.test/jobs/paid",
        )
        unpaid_job = job_repo.get_or_create_job(
            title="Data Engineer",
            company=company,
            canonical_url="https://example.test/jobs/unpaid",
        )
        job_repo.upsert_source_listing(
            source="lever",
            source_job_id="lever:paid",
            job=paid_job,
            salary_min=6000,
            salary_max=8000,
            salary_currency="SGD",
            salary_interval="monthly",
        )
        job_repo.upsert_source_listing(
            source="greenhouse",
            source_job_id="greenhouse:unpaid",
            job=unpaid_job,
        )
        session.commit()

        coverage = salary_coverage(session, days=30)

        assert coverage.total_posting_count == 2
        assert coverage.salary_posting_count == 1
        assert coverage.disclosure_rate == 0.5


def test_salary_reports_ignore_latest_inactive_listing_observation(tmp_path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'inactive.sqlite3'}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        job_repo = JobRepository(session)
        company = job_repo.get_or_create_company(name="Example")
        job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=company,
            canonical_url="https://example.test/jobs/inactive",
        )
        listing = job_repo.upsert_source_listing(
            source="lever",
            source_job_id="lever:inactive",
            job=job,
            salary_min=6000,
            salary_max=8000,
            salary_currency="SGD",
            salary_interval="monthly",
        )
        job_repo.record_observation(source_listing=listing, is_active=True)
        session.flush()
        job_repo.record_observation(source_listing=listing, is_active=False)
        session.commit()

        assert salary_range_summaries(session, days=30) == []
        assert top_salary_listings(session, days=30) == []
