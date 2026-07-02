from roleradar.analytics.salary_trends import salary_range_summaries
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
    assert summaries[0].min_salary == 6000
    assert summaries[0].max_salary == 9000
    assert summaries[0].average_min_salary == 6500
    assert summaries[0].average_max_salary == 8500
    assert summaries[0].average_midpoint == 7500
