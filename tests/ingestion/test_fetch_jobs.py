from sqlalchemy import select

from roleradar.ingestion.fetch_jobs import ingest_jobs, read_target_companies
from roleradar.sources.seed_loader import load_taxonomy_seed
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.models import JobSkill, PostingObservation, SourceListing


class FakeLeverClient:
    def fetch_postings(self, site: str) -> list[dict]:
        assert site == "example"
        return [
            {
                "id": "job-1",
                "text": "Data Analyst",
                "hostedUrl": "https://jobs.lever.co/example/job-1",
                "categories": {"location": "Singapore", "commitment": "Full-time"},
                "descriptionPlain": "Python and SQL role.",
            }
        ]


def test_read_target_companies_filters_enabled_later(tmp_path) -> None:
    targets_file = tmp_path / "targets.csv"
    targets_file.write_text(
        "\n".join(
            [
                "company_name,source,board_token_or_site,enabled,notes",
                "Example,lever,example,true,",
                "Disabled,lever,disabled,false,",
            ]
        ),
        encoding="utf-8",
    )

    targets = read_target_companies(targets_file)

    assert len(targets) == 2
    assert targets[0].enabled is True
    assert targets[1].enabled is False


def test_ingest_jobs_uses_lever_target_and_extracts_skills(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'ingest.sqlite3'}"
    seed_file = tmp_path / "skills.csv"
    targets_file = tmp_path / "targets.csv"
    seed_file.write_text(
        "\n".join(
            [
                "skill_name,category,source_taxonomy,alias,match_type,case_sensitive",
                "Python,Tech,local,Python,literal,false",
                "SQL,Tech,local,SQL,literal,false",
            ]
        ),
        encoding="utf-8",
    )
    targets_file.write_text(
        "\n".join(
            [
                "company_name,source,board_token_or_site,enabled,notes",
                "Example Pte Ltd,lever,example,true,",
            ]
        ),
        encoding="utf-8",
    )

    engine = create_database_engine(db_url)
    init_database(engine=engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        load_taxonomy_seed(session, seed_file)
        session.commit()

    result = ingest_jobs(
        database_url=db_url,
        source="lever",
        targets_file=targets_file,
        lever_client=FakeLeverClient(),
    )

    assert result.targets_seen == 1
    assert result.targets_ingested == 1
    assert result.jobs_seen == 1
    assert result.source_listings_upserted == 1
    assert result.observations_created == 1
    assert result.job_skills_extracted == 2

    with session_factory() as session:
        listings = session.scalars(select(SourceListing)).all()
        observations = session.scalars(select(PostingObservation)).all()
        job_skills = session.scalars(select(JobSkill)).all()

    assert len(listings) == 1
    assert listings[0].source_job_id == "example:job-1"
    assert len(observations) == 1
    assert len(job_skills) == 2

