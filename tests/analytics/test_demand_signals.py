from datetime import UTC, datetime, timedelta

from roleradar.analytics.demand_signals import (
    active_listings_by_company,
    active_listings_by_company_and_role_family,
    active_listings_summary,
    company_hiring_breadth,
    new_listings_by_company,
)
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.repositories import JobRepository


def test_company_demand_signals_count_active_and_new_listings(tmp_path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'demand.sqlite3'}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        job_repo = JobRepository(session)
        alpha = job_repo.get_or_create_company(name="Alpha")
        beta = job_repo.get_or_create_company(name="Beta")
        alpha_data = job_repo.get_or_create_job(
            title="Data Engineer",
            company=alpha,
            canonical_url="https://example.test/jobs/alpha-data",
            role_family_id="data_engineer",
        )
        alpha_ai = job_repo.get_or_create_job(
            title="AI Engineer",
            company=alpha,
            canonical_url="https://example.test/jobs/alpha-ai",
            role_family_id="ai_ml_engineer",
        )
        beta_job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=beta,
            canonical_url="https://example.test/jobs/beta-data",
            role_family_id="data_analyst",
        )
        alpha_data_listing = job_repo.upsert_source_listing(
            source="careers_gov",
            source_job_id="alpha-data",
            job=alpha_data,
            salary_min=6000,
            salary_max=8000,
        )
        alpha_ai_listing = job_repo.upsert_source_listing(
            source="careers_gov",
            source_job_id="alpha-ai",
            job=alpha_ai,
        )
        beta_listing = job_repo.upsert_source_listing(
            source="careers_gov",
            source_job_id="beta-data",
            job=beta_job,
        )
        beta_listing.first_seen_at = datetime.now(UTC) - timedelta(days=20)
        job_repo.record_observation(source_listing=alpha_data_listing)
        job_repo.record_observation(source_listing=alpha_ai_listing)
        job_repo.record_observation(source_listing=beta_listing)
        session.commit()

        summary = active_listings_summary(session)
        companies = active_listings_by_company(session, limit=10)
        matrix = active_listings_by_company_and_role_family(session, limit=10)
        new_rows = new_listings_by_company(session, days=7, limit=10)
        breadth = company_hiring_breadth(session, limit=10)

    assert summary.active_listing_count == 3
    assert summary.new_listing_count_7d == 2
    assert summary.company_count == 2
    assert companies[0].company_name == "Alpha"
    assert companies[0].active_listing_count == 2
    assert companies[0].new_listing_count_7d == 2
    assert companies[0].role_family_count == 2
    assert companies[0].salary_disclosure_rate == 0.5
    assert {row.role_family_id for row in matrix if row.company_name == "Alpha"} == {
        "ai_ml_engineer",
        "data_engineer",
    }
    assert new_rows == [
        type(new_rows[0])(company_name="Alpha", new_listing_count=2)
    ]
    assert breadth[0].company_name == "Alpha"
    assert breadth[0].role_family_count == 2
