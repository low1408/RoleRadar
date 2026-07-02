from sqlalchemy import select

from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.models import PostingObservation, SourceListing
from roleradar.storage.repositories import IngestionRunRepository, JobRepository


def test_source_listing_upsert_preserves_provenance_and_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "roleradar.sqlite3"
    engine = create_database_engine(f"sqlite:///{db_path}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        run_repo = IngestionRunRepository(session)
        job_repo = JobRepository(session)

        run = run_repo.create(source="lever", parameters={"target": "example"})
        company = job_repo.get_or_create_company(name="Example Pte Ltd")
        job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=company,
            canonical_url="https://jobs.example.com/data-analyst",
            location="Singapore",
            description_text="Python and SQL role",
            content_hash="hash-v1",
            raw_payload={"id": "job-1"},
        )
        first_listing = job_repo.upsert_source_listing(
            source="lever",
            source_job_id="job-1",
            ingestion_run=run,
            job=job,
            canonical_url="https://jobs.example.com/data-analyst",
            source_url="https://api.lever.co/v0/postings/example/job-1",
            source_company_name="Example Pte Ltd",
            source_title="Data Analyst",
            location="Singapore",
            description_text="Python and SQL role",
            content_hash="hash-v1",
            raw_payload={"id": "job-1", "version": 1},
        )
        first_observation = job_repo.record_observation(
            source_listing=first_listing,
            ingestion_run=run,
            content_hash="hash-v1",
            raw_payload={"id": "job-1", "version": 1},
        )
        run_repo.complete(run)
        session.commit()

        first_listing_id = first_listing.id
        first_observation_id = first_observation.id

    with session_factory() as session:
        run_repo = IngestionRunRepository(session)
        job_repo = JobRepository(session)

        second_run = run_repo.create(source="lever", parameters={"target": "example"})
        second_listing = job_repo.upsert_source_listing(
            source="lever",
            source_job_id="job-1",
            ingestion_run=second_run,
            canonical_url="https://jobs.example.com/data-analyst",
            source_url="https://api.lever.co/v0/postings/example/job-1",
            source_company_name="Example Pte Ltd",
            source_title="Data Analyst",
            location="Singapore",
            description_text="Python, SQL, and Tableau role",
            content_hash="hash-v2",
            raw_payload={"id": "job-1", "version": 2},
        )
        second_observation = job_repo.record_observation(
            source_listing=second_listing,
            ingestion_run=second_run,
            content_hash="hash-v2",
            raw_payload={"id": "job-1", "version": 2},
        )
        run_repo.complete(second_run)
        session.commit()

        assert second_listing.id == first_listing_id
        assert second_observation.id != first_observation_id

    with session_factory() as session:
        listings = session.scalars(select(SourceListing)).all()
        observations = session.scalars(select(PostingObservation)).all()

    assert len(listings) == 1
    assert listings[0].source == "lever"
    assert listings[0].source_job_id == "job-1"
    assert listings[0].source_company_name == "Example Pte Ltd"
    assert listings[0].content_hash == "hash-v2"
    assert len(observations) == 2


def test_company_and_job_get_or_create_are_stable(tmp_path) -> None:
    db_path = tmp_path / "roleradar.sqlite3"
    engine = create_database_engine(f"sqlite:///{db_path}")
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        repo = JobRepository(session)
        company = repo.get_or_create_company(name="Example Pte Ltd")
        same_company = repo.get_or_create_company(name=" example  pte ltd ")
        job = repo.get_or_create_job(
            title="Data Analyst",
            company=company,
            canonical_url="https://jobs.example.com/data-analyst",
        )
        same_job = repo.get_or_create_job(
            title="Data Analyst",
            company=same_company,
            canonical_url="https://jobs.example.com/data-analyst",
        )

    assert same_company.id == company.id
    assert same_job.id == job.id

