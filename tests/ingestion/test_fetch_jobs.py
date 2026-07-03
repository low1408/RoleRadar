from sqlalchemy import select

from roleradar.ingestion.fetch_jobs import ingest_jobs, read_target_companies
from roleradar.sources.seed_loader import load_taxonomy_seed
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.models import (
    DuplicateJobCandidate,
    JobSkill,
    PostingObservation,
    SourceListing,
)


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


class FakeGreenhouseClient:
    def fetch_postings(self, site: str) -> list[dict]:
        assert site in {"example", "example-gh"}
        return [
            {
                "id": 123,
                "title": "Data Analyst",
                "absolute_url": f"https://boards.greenhouse.io/{site}/jobs/123",
                "location": {"name": "Singapore"},
                "content": "<p>Python and SQL role.</p>",
                "updated_at": "2026-07-01T01:02:03Z",
            }
        ]


class FakeAdzunaClient:
    def search_jobs(
        self,
        *,
        query: str,
        location: str,
        country: str = "sg",
        results_per_page: int = 20,
    ) -> list[dict]:
        assert query == "data analyst"
        assert location == "Singapore"
        assert country == "sg"
        assert results_per_page == 20
        return [
            {
                "id": "adzuna-1",
                "title": "Data Analyst",
                "redirect_url": "https://www.adzuna.sg/jobs/details/adzuna-1",
                "description": "Python and SQL snippet...",
                "created": "2026-07-01T01:02:03Z",
                "salary_min": 5000,
                "salary_max": 7000,
                "company": {"display_name": "Example Pte Ltd"},
                "location": {"display_name": "Singapore"},
                "contract_time": "full_time",
            }
        ]


class FakeCareersGovClient:
    def search_jobs(
        self,
        *,
        query: str | None = None,
        limit: int = 20,
        max_pages: int = 1,
    ) -> list[dict]:
        assert query == "data analyst"
        assert limit == 20
        assert max_pages == 2
        return [
            {
                "uuid": "mcf-1",
                "metadata": {
                    "jobPostId": "post-1",
                    "updatedAt": "2026-07-01T01:02:03Z",
                },
                "title": "Data Analyst",
                "description": "<p>Python and SQL role.</p>",
                "postedCompany": {"name": "Example Pte Ltd"},
                "salary": {
                    "minimum": 5000,
                    "maximum": 7000,
                    "type": {"salaryType": "Monthly"},
                },
                "employmentTypes": [{"employmentType": "Full Time"}],
                "_links": {
                    "self": {
                        "href": "https://api1.mycareersfuture.sg/v2/jobs/mcf-1",
                    }
                },
            }
        ]


class FakeJobstreetClient:
    def search_jobs(
        self,
        *,
        query: str,
        location: str,
        max_pages: int = 1,
    ) -> list[dict]:
        assert query == "data analyst"
        assert location == "Singapore"
        assert max_pages == 2
        return [
            {
                "id": "jobstreet-1",
                "title": "Data Analyst",
                "jobUrl": "/job/123",
                "companyName": "Example Pte Ltd",
                "locations": [{"label": "Singapore"}],
                "workTypes": [{"label": "Full time"}],
                "teaser": "Python and SQL role.",
                "salaryLabel": "$5,000 - $7,000 per month",
                "listingDate": "2026-07-01T01:02:03Z",
            }
        ]


class FakeFailingJobstreetClient:
    def search_jobs(
        self,
        *,
        query: str,
        location: str,
        max_pages: int = 1,
    ) -> list[dict]:
        raise RuntimeError("Jobstreet returned a Cloudflare challenge")


class PartiallyFailingGreenhouseClient:
    def fetch_postings(self, site: str) -> list[dict]:
        if site == "broken":
            raise RuntimeError("source unavailable")
        return [
            {
                "id": 124,
                "title": "Software Engineer",
                "absolute_url": "https://boards.greenhouse.io/example/jobs/124",
                "location": {"name": "Singapore"},
                "content": "<p>Python services.</p>",
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
    _write_seed_file(seed_file)
    targets_file.write_text(
        "\n".join(
            [
                "company_name,source,board_token_or_site,enabled,notes",
                "Example Pte Ltd,lever,example,true,",
            ]
        ),
        encoding="utf-8",
    )
    _seed_taxonomy(db_url, seed_file)

    result = ingest_jobs(
        database_url=db_url,
        source="lever",
        targets_file=targets_file,
        lever_client=FakeLeverClient(),
    )

    assert result.targets_seen == 1
    assert result.targets_ingested == 1
    assert result.targets_failed == 0
    assert result.jobs_seen == 1
    assert result.source_listings_upserted == 1
    assert result.observations_created == 1
    assert result.job_skills_extracted == 2
    assert result.duplicate_candidates == 0

    engine = create_database_engine(db_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        listings = session.scalars(select(SourceListing)).all()
        observations = session.scalars(select(PostingObservation)).all()
        job_skills = session.scalars(select(JobSkill)).all()

    assert len(listings) == 1
    assert listings[0].source_job_id == "example:job-1"
    assert len(observations) == 1
    assert len(job_skills) == 2


def test_ingest_jobs_uses_greenhouse_target(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'greenhouse.sqlite3'}"
    seed_file = tmp_path / "skills.csv"
    targets_file = tmp_path / "targets.csv"
    _write_seed_file(seed_file)
    targets_file.write_text(
        "\n".join(
            [
                "company_name,source,board_token_or_site,enabled,notes",
                "Example Pte Ltd,greenhouse,example,true,",
            ]
        ),
        encoding="utf-8",
    )
    _seed_taxonomy(db_url, seed_file)

    result = ingest_jobs(
        database_url=db_url,
        source="greenhouse",
        targets_file=targets_file,
        greenhouse_client=FakeGreenhouseClient(),
    )

    assert result.targets_ingested == 1
    assert result.targets_failed == 0
    assert result.jobs_seen == 1
    assert result.source_listings_upserted == 1
    assert result.job_skills_extracted == 2

    engine = create_database_engine(db_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        listing = session.scalars(select(SourceListing)).one()

    assert listing.source == "greenhouse"
    assert listing.source_job_id == "example:123"
    assert listing.description_text == "Python and SQL role."


def test_cross_source_duplicate_candidate_keeps_source_listings(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'duplicates.sqlite3'}"
    seed_file = tmp_path / "skills.csv"
    lever_targets = tmp_path / "lever-targets.csv"
    greenhouse_targets = tmp_path / "greenhouse-targets.csv"
    _write_seed_file(seed_file)
    lever_targets.write_text(
        "\n".join(
            [
                "company_name,source,board_token_or_site,enabled,notes",
                "Example Pte Ltd,lever,example,true,",
            ]
        ),
        encoding="utf-8",
    )
    greenhouse_targets.write_text(
        "\n".join(
            [
                "company_name,source,board_token_or_site,enabled,notes",
                "Example Pte Ltd,greenhouse,example-gh,true,",
            ]
        ),
        encoding="utf-8",
    )
    _seed_taxonomy(db_url, seed_file)

    ingest_jobs(
        database_url=db_url,
        source="lever",
        targets_file=lever_targets,
        lever_client=FakeLeverClient(),
    )
    result = ingest_jobs(
        database_url=db_url,
        source="greenhouse",
        targets_file=greenhouse_targets,
        greenhouse_client=FakeGreenhouseClient(),
    )

    assert result.duplicate_candidates == 1

    engine = create_database_engine(db_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        listings = session.scalars(select(SourceListing)).all()
        candidates = session.scalars(select(DuplicateJobCandidate)).all()

    assert len(listings) == 2
    assert {listing.source for listing in listings} == {"lever", "greenhouse"}
    assert len({listing.job_id for listing in listings}) == 2
    assert len(candidates) == 1
    assert candidates[0].status == "pending"


def test_target_failure_does_not_fail_whole_ingestion_run(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'partial-failure.sqlite3'}"
    seed_file = tmp_path / "skills.csv"
    targets_file = tmp_path / "targets.csv"
    _write_seed_file(seed_file)
    targets_file.write_text(
        "\n".join(
            [
                "company_name,source,board_token_or_site,enabled,notes",
                "Broken,greenhouse,broken,true,",
                "Example,greenhouse,example,true,",
            ]
        ),
        encoding="utf-8",
    )
    _seed_taxonomy(db_url, seed_file)

    result = ingest_jobs(
        database_url=db_url,
        source="greenhouse",
        targets_file=targets_file,
        greenhouse_client=PartiallyFailingGreenhouseClient(),
    )

    assert result.targets_seen == 2
    assert result.targets_ingested == 1
    assert result.targets_failed == 1
    assert result.jobs_seen == 1


def test_ingest_jobs_uses_adzuna_query_without_extracting_snippet_skills(
    tmp_path,
) -> None:
    db_url = f"sqlite:///{tmp_path / 'adzuna.sqlite3'}"
    seed_file = tmp_path / "skills.csv"
    _write_seed_file(seed_file)
    _seed_taxonomy(db_url, seed_file)

    result = ingest_jobs(
        database_url=db_url,
        source="adzuna",
        query="data analyst",
        location="Singapore",
        adzuna_client=FakeAdzunaClient(),
    )

    assert result.targets_seen == 1
    assert result.targets_ingested == 1
    assert result.targets_failed == 0
    assert result.jobs_seen == 1
    assert result.source_listings_upserted == 1
    assert result.observations_created == 1
    assert result.job_skills_extracted == 0

    engine = create_database_engine(db_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        listing = session.scalars(select(SourceListing)).one()
        job_skills = session.scalars(select(JobSkill)).all()

    assert listing.source == "adzuna"
    assert listing.raw_payload["text_quality"] == "snippet"
    assert listing.salary_min == 5000
    assert listing.salary_max == 7000
    assert job_skills == []


def test_ingest_jobs_uses_careers_gov_when_experimental_enabled(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'careers-gov.sqlite3'}"
    seed_file = tmp_path / "skills.csv"
    _write_seed_file(seed_file)
    _seed_taxonomy(db_url, seed_file)

    result = ingest_jobs(
        database_url=db_url,
        source="careers_gov",
        query="data analyst",
        max_pages=2,
        careers_gov_throttle_seconds=0,
        careers_gov_client=FakeCareersGovClient(),
    )

    assert result.targets_seen == 1
    assert result.targets_ingested == 1
    assert result.targets_failed == 0
    assert result.jobs_seen == 1
    assert result.source_listings_upserted == 1
    assert result.observations_created == 1
    assert result.job_skills_extracted == 2

    engine = create_database_engine(db_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        listing = session.scalars(select(SourceListing)).one()
        job_skills = session.scalars(select(JobSkill)).all()

    assert listing.source == "careers_gov"
    assert listing.source_job_id == "mcf-1"
    assert listing.raw_payload["source_api"] == "mycareersfuture"
    assert listing.salary_min == 5000
    assert listing.salary_max == 7000
    assert len(job_skills) == 2


def test_ingest_jobs_uses_jobstreet_query_without_targets(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'jobstreet.sqlite3'}"
    seed_file = tmp_path / "skills.csv"
    _write_seed_file(seed_file)
    _seed_taxonomy(db_url, seed_file)

    result = ingest_jobs(
        database_url=db_url,
        source="jobstreet",
        query="data analyst",
        location="Singapore",
        max_pages=2,
        jobstreet_client=FakeJobstreetClient(),
    )

    assert result.targets_seen == 1
    assert result.targets_ingested == 1
    assert result.targets_failed == 0
    assert result.jobs_seen == 1
    assert result.source_listings_upserted == 1
    assert result.observations_created == 1
    assert result.job_skills_extracted == 0

    engine = create_database_engine(db_url)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        listing = session.scalars(select(SourceListing)).one()
        assert listing.source == "jobstreet"
        assert listing.source_job_id == "jobstreet-1"
        assert listing.salary_min == 5000
        assert listing.salary_max == 7000
        assert listing.raw_payload["text_quality"] == "snippet"


def test_ingest_jobs_returns_jobstreet_source_error(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path / 'jobstreet-failed.sqlite3'}"

    result = ingest_jobs(
        database_url=db_url,
        source="jobstreet",
        query="data analyst",
        location="Singapore",
        jobstreet_client=FakeFailingJobstreetClient(),
    )

    assert result.targets_seen == 1
    assert result.targets_ingested == 0
    assert result.targets_failed == 1
    assert result.jobs_seen == 0
    assert result.error_message is not None
    assert "Cloudflare challenge" in result.error_message


def _write_seed_file(seed_file) -> None:
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


def _seed_taxonomy(db_url: str, seed_file) -> None:
    engine = create_database_engine(db_url)
    init_database(engine=engine)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        load_taxonomy_seed(session, seed_file)
        session.commit()
