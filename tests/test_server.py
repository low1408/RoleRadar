from __future__ import annotations

import sqlite3

from sqlalchemy import select

from roleradar.app.server import create_app
from roleradar.config.settings import Settings
from roleradar.ingestion.fetch_jobs import IngestionResult
from roleradar.storage.models import (
    DuplicateAuditLog,
    Job,
    PostingObservation,
    SourceListing,
)
from roleradar.storage.repositories import JobRepository, SkillRepository


def test_health_and_overview_return_metadata(tmp_path) -> None:
    app = _seed_app(tmp_path)
    health_endpoint = _endpoint(app, "/api/v1/health")
    overview_endpoint = _endpoint(app, "/api/v1/analytics/overview")

    with app.state.session_factory() as session:
        health = health_endpoint(session=session)
        overview = overview_endpoint(days=30, session=session)

    assert health["status"] == "ok"
    payload = overview
    assert payload["meta"]["total_records_in_db"] == 1
    assert payload["data"]["kpis"]["canonical_jobs"] == 1
    assert payload["data"]["top_skills"] == [
        {"skill_name": "Python", "job_count": 1}
    ]
    company_row = payload["data"]["top_hiring_companies"][0]
    assert company_row["company_name"] == "Example Pte Ltd"
    assert company_row["job_count"] == 1
    assert company_row["source_listing_count"] == 1
    assert company_row["latest_seen_at"] is not None
    assert company_row["top_role_families"] == [
        {"role_family": "Data Analyst", "job_count": 1}
    ]
    assert company_row["top_sources"] == [{"source": "lever", "posting_count": 1}]
    demand_row = payload["data"]["company_demand_signals"][0]
    assert demand_row["company_name"] == "Example Pte Ltd"
    assert demand_row["active_listing_count"] == 1
    assert demand_row["new_listing_count_7d"] == 1
    assert "Current snapshot only" in payload["data"]["trend_caveat"]


def test_demand_signals_endpoint_returns_company_rankings(tmp_path) -> None:
    app = _seed_app(tmp_path)
    demand_endpoint = _endpoint(app, "/api/v1/analytics/demand-signals")

    with app.state.session_factory() as session:
        payload = demand_endpoint(days=7, limit=10, session=session)

    assert payload["data"]["summary"]["active_listing_count"] == 1
    assert payload["data"]["companies"][0]["company_name"] == "Example Pte Ltd"
    assert payload["data"]["companies"][0]["active_listing_count"] == 1
    assert payload["data"]["new_listings_by_company"][0]["new_listing_count"] == 1
    assert "Repeated observations are not counted" in payload["data"]["caveat"]


def test_individual_trend_endpoints_return_wrapped_rows(tmp_path) -> None:
    app = _seed_app(tmp_path)
    skill_endpoint = _endpoint(app, "/api/v1/analytics/trends/skills/{skill_name}")
    salary_endpoint = _endpoint(app, "/api/v1/analytics/trends/salary/{family_id}")
    velocity_endpoint = _endpoint(app, "/api/v1/analytics/trends/velocity")
    company_velocity_endpoint = _endpoint(
        app,
        "/api/v1/analytics/trends/company-velocity",
    )

    with app.state.session_factory() as session:
        skill_payload = skill_endpoint(skill_name="Python", weeks=4, session=session)
        salary_payload = salary_endpoint(
            family_id="data_analyst",
            weeks=4,
            session=session,
        )
        velocity_payload = velocity_endpoint(
            weeks=4,
            role_family=None,
            session=session,
        )
        company_velocity_payload = company_velocity_endpoint(
            weeks=4,
            role_family=None,
            limit=10,
            session=session,
        )

    assert skill_payload["data"]["skill_name"] == "Python"
    assert len(skill_payload["data"]["items"]) == 4
    assert salary_payload["data"]["role_family"] == "data_analyst"
    assert len(salary_payload["data"]["items"]) == 4
    assert len(velocity_payload["data"]["items"]) == 4
    assert company_velocity_payload["data"]["items"][0]["company_name"] == (
        "Example Pte Ltd"
    )


def test_overview_can_be_scoped_to_role_family(tmp_path) -> None:
    app = _seed_app(tmp_path)
    overview_endpoint = _endpoint(app, "/api/v1/analytics/overview")

    with app.state.session_factory() as session:
        skill_repo = SkillRepository(session)
        pytorch = skill_repo.get_or_create_skill(name="PyTorch")
        job_repo = JobRepository(session)
        ai_company = job_repo.get_or_create_company(name="AI Labs Pte Ltd")
        ai_job = job_repo.get_or_create_job(
            title="Machine Learning Engineer",
            company=ai_company,
            canonical_url="https://example.test/jobs/ml",
            location="Singapore",
            description_text="Build PyTorch models.",
        )
        skill_repo.add_job_skill(
            job=ai_job,
            skill=pytorch,
            confidence=1.0,
            extraction_method="test",
            matched_text="PyTorch",
        )
        ai_listing = job_repo.upsert_source_listing(
            source="greenhouse",
            source_job_id="ml-1",
            job=ai_job,
            canonical_url="https://example.test/jobs/ml",
            source_url="https://greenhouse.test/ml-1",
            source_company_name="AI Labs Pte Ltd",
            source_title="Machine Learning Engineer",
            location="Singapore",
            description_text="Build PyTorch models.",
        )
        job_repo.record_observation(source_listing=ai_listing)
        session.commit()

    with app.state.session_factory() as session:
        global_payload = overview_endpoint(
            days=30,
            role_family=None,
            session=session,
        )

    with app.state.session_factory() as session:
        payload = overview_endpoint(
            days=30,
            role_family="data_analyst",
            session=session,
        )

    assert global_payload["data"]["kpis"]["canonical_jobs"] == 2
    assert global_payload["data"]["top_skills"] == [
        {"skill_name": "PyTorch", "job_count": 1},
        {"skill_name": "Python", "job_count": 1},
    ]
    assert payload["meta"]["applied_filters"]["role_family"] == "data_analyst"
    assert payload["meta"]["sample_size"] == 1
    assert payload["data"]["selected_role_family"]["id"] == "data_analyst"
    assert payload["data"]["kpis"]["canonical_jobs"] == 1
    assert payload["data"]["kpis"]["companies"] == 1
    assert payload["data"]["top_skills"] == [
        {"skill_name": "Python", "job_count": 1}
    ]
    assert payload["data"]["top_hiring_companies"] == [
        {
            "company_name": "Example Pte Ltd",
            "job_count": 1,
            "source_listing_count": 1,
            "latest_seen_at": payload["data"]["top_hiring_companies"][0][
                "latest_seen_at"
            ],
            "top_role_families": [
                {"role_family": "Data Analyst", "job_count": 1}
            ],
            "top_sources": [{"source": "lever", "posting_count": 1}],
        }
    ]
    assert payload["data"]["top_hiring_companies"][0]["company_name"] == (
        "Example Pte Ltd"
    )
    assert payload["data"]["salary"]["by_source"][0]["group"] == "lever"


def test_jobs_endpoint_paginates_and_wraps_response(tmp_path) -> None:
    app = _seed_app(tmp_path)
    jobs_endpoint = _endpoint(app, "/api/v1/jobs")

    with app.state.session_factory() as session:
        payload = jobs_endpoint(
            limit=10,
            offset=0,
            sort_by="company",
            order="asc",
            source=None,
            role_family=None,
            q=None,
            session=session,
        )
        role_filtered = jobs_endpoint(
            limit=10,
            offset=0,
            sort_by="company",
            order="asc",
            source=None,
            role_family="data_analyst",
            q=None,
            session=session,
        )
        role_miss = jobs_endpoint(
            limit=10,
            offset=0,
            sort_by="company",
            order="asc",
            source=None,
            role_family="ai_ml_engineer",
            q=None,
            session=session,
        )

    assert payload["meta"]["sample_size"] == 1
    assert payload["data"]["total"] == 1
    assert payload["data"]["items"][0]["title"] == "Data Analyst"
    assert payload["data"]["items"][0]["role_family"]["id"] == "data_analyst"
    assert payload["data"]["items"][0]["salary_midpoint"] == 7000
    assert "Support data mapping" in payload["data"]["items"][0]["responsibilities"]
    assert role_filtered["data"]["total"] == 1
    assert role_miss["data"]["total"] == 0


def test_jobs_csv_export_returns_database_listing_rows(tmp_path) -> None:
    app = _seed_app(tmp_path)
    csv_endpoint = _endpoint(app, "/api/v1/jobs/export.csv")

    with app.state.session_factory() as session:
        response = csv_endpoint(source=None, q=None, session=session)

    body = response.body.decode()
    assert response.media_type == "text/csv; charset=utf-8"
    assert "job_id,source_listing_id,title,company_name,source" in body
    assert "Data Analyst,Example Pte Ltd,lever" in body
    assert "SGD,monthly,7000" in body
    assert "Support data mapping between Salesforce and external systems" in body
    assert "Minimum 4 years of experience in data analysis" in body


def test_duplicate_resolution_writes_audit_log(tmp_path) -> None:
    app = _seed_app(tmp_path, duplicate=True)
    list_endpoint = _endpoint(app, "/api/v1/admin/duplicates")
    resolve_endpoint = _endpoint(
        app, "/api/v1/admin/duplicates/{duplicate_candidate_id}/resolve", method="POST"
    )

    with app.state.session_factory() as session:
        duplicates = list_endpoint(
            limit=20,
            offset=0,
            status="pending",
            session=session,
        )
        duplicate_id = duplicates["data"]["items"][0]["id"]
        response = resolve_endpoint(
            duplicate_candidate_id=duplicate_id,
            payload={
                "action": "dismiss",
                "reason": "Different requisitions",
                "expected_status": "pending",
            },
            session=session,
        )

    payload = response["data"]
    assert payload["duplicate_candidate"]["status"] == "dismissed"
    assert payload["audit_log"]["previous_status"] == "pending"
    assert payload["audit_log"]["new_status"] == "dismissed"

    with app.state.session_factory() as session:
        audit_log = session.scalar(select(DuplicateAuditLog))
    assert audit_log is not None
    assert audit_log.reason == "Different requisitions"


def test_duplicate_merge_moves_source_listings_and_closes_redundant_job(
    tmp_path,
) -> None:
    app = _seed_app(tmp_path, duplicate=True)
    list_endpoint = _endpoint(app, "/api/v1/admin/duplicates")
    overview_endpoint = _endpoint(app, "/api/v1/analytics/overview")
    resolve_endpoint = _endpoint(
        app, "/api/v1/admin/duplicates/{duplicate_candidate_id}/resolve", method="POST"
    )

    with app.state.session_factory() as session:
        duplicates = list_endpoint(
            limit=20,
            offset=0,
            status="pending",
            session=session,
        )
        duplicate_id = duplicates["data"]["items"][0]["id"]
        response = resolve_endpoint(
            duplicate_candidate_id=duplicate_id,
            payload={
                "action": "merge",
                "reason": "Same requisition",
                "expected_status": "pending",
            },
            session=session,
        )

    assert response["data"]["duplicate_candidate"]["status"] == "merged"
    assert response["data"]["audit_log"]["new_status"] == "merged"

    with app.state.session_factory() as session:
        listings = session.scalars(select(SourceListing)).all()
        jobs = session.scalars(select(Job)).all()
        overview = overview_endpoint(days=30, role_family=None, session=session)

    assert len({listing.job_id for listing in listings}) == 1
    assert len([job for job in jobs if job.closed_at is not None]) == 1
    assert overview["data"]["kpis"]["canonical_jobs"] == 1


def test_admin_dedupe_scan_creates_candidates_for_existing_duplicate_listings(
    tmp_path,
) -> None:
    app = _seed_app(tmp_path)
    list_endpoint = _endpoint(app, "/api/v1/admin/duplicates")
    dedupe_endpoint = _endpoint(
        app,
        "/api/v1/admin/source-listings/dedupe",
        method="POST",
    )
    duplicate_description = (
        "Responsibilities Support data mapping between Salesforce and external "
        "systems. Required competencies and certifications Minimum 4 years of "
        "experience in data analysis. Preferred competencies and qualifications "
        "Interest or exposure to Salesforce."
    )

    with app.state.session_factory() as session:
        existing_job = session.scalars(select(Job)).first()
        job_repo = JobRepository(session)
        duplicate_job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=existing_job.company,
            canonical_url="https://example.test/jobs/admin-dedupe-copy",
            location="Singapore",
            description_text="Different source body with same structured listing.",
        )
        duplicate_listing = job_repo.upsert_source_listing(
            source="greenhouse",
            source_job_id="admin-dedupe-copy",
            job=duplicate_job,
            canonical_url="https://example.test/jobs/admin-dedupe-copy",
            source_url="https://greenhouse.test/admin-dedupe-copy",
            source_company_name="Example Pte Ltd",
            source_title="Data Analyst",
            location="Singapore",
            description_text=duplicate_description,
            salary_min=6000,
            salary_max=8000,
            salary_currency="SGD",
            salary_interval="monthly",
        )
        job_repo.record_observation(source_listing=duplicate_listing)
        session.commit()

    with app.state.session_factory() as session:
        before = list_endpoint(
            limit=20,
            offset=0,
            status="pending",
            session=session,
        )
        response = dedupe_endpoint(session=session)
        after = list_endpoint(
            limit=20,
            offset=0,
            status="pending",
            session=session,
        )

    assert before["data"]["total"] == 0
    assert response["data"]["duplicate_candidate_pairs_found"] == 1
    assert response["data"]["duplicate_candidates_created"] == 1
    assert after["data"]["total"] == 1
    assert after["data"]["items"][0]["match_type"] == "structured_fields"
    assert "matching responsibilities" in after["data"]["items"][0]["reason"]


def test_admin_dedupe_removes_same_source_field_equivalent_listings(
    tmp_path,
) -> None:
    app = _seed_app(tmp_path)
    dedupe_endpoint = _endpoint(
        app,
        "/api/v1/admin/source-listings/dedupe",
        method="POST",
    )
    duplicate_description = (
        "Responsibilities Support data mapping between Salesforce and external "
        "systems. Required competencies and certifications Minimum 4 years of "
        "experience in data analysis. Preferred competencies and qualifications "
        "Interest or exposure to Salesforce."
    )

    with app.state.session_factory() as session:
        existing_listing = session.scalars(select(SourceListing)).one()
        existing_listing.content_hash = "same-content"
        existing_listing.job.content_hash = "same-content"
        job_repo = JobRepository(session)
        duplicate_job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=existing_listing.job.company,
            canonical_url="https://example.test/jobs/same-source-copy",
            location="Singapore",
            description_text=duplicate_description,
            content_hash="same-content",
        )
        duplicate_listing = job_repo.upsert_source_listing(
            source="lever",
            source_job_id="job-1-copy",
            job=duplicate_job,
            canonical_url="https://example.test/jobs/same-source-copy",
            source_url="https://lever.test/job-1-copy",
            source_company_name="Example Pte Ltd",
            source_title="Data Analyst",
            location="Singapore",
            description_text=duplicate_description,
            salary_min=6000,
            salary_max=8000,
            salary_currency="SGD",
            salary_interval="monthly",
            content_hash="same-content",
        )
        job_repo.record_observation(source_listing=duplicate_listing)
        session.commit()

    with app.state.session_factory() as session:
        response = dedupe_endpoint(session=session)

    assert response["data"]["field_duplicate_groups_before"] == 1
    assert response["data"]["field_duplicate_groups_after"] == 0
    assert response["data"]["field_groups_merged"] == 1
    assert response["data"]["source_listings_removed"] == 1
    assert response["data"]["redundant_jobs_closed"] == 1

    with app.state.session_factory() as session:
        listings = session.scalars(select(SourceListing)).all()
        active_jobs = session.scalars(
            select(Job).where(Job.closed_at.is_(None))
        ).all()

    assert len(listings) == 1
    assert len(active_jobs) == 1


def test_source_listing_dedupe_endpoint_merges_legacy_duplicate_source_ids(
    tmp_path,
) -> None:
    db_path = tmp_path / "legacy-source-listings.sqlite3"
    _create_legacy_source_listings_table(db_path)
    app = create_app(Settings(database_url=f"sqlite:///{db_path}"))
    list_endpoint = _endpoint(app, "/api/v1/admin/duplicates")
    dedupe_endpoint = _endpoint(
        app,
        "/api/v1/admin/source-listings/dedupe",
        method="POST",
    )

    with app.state.session_factory() as session:
        older = SourceListing(
            source="careers_gov",
            source_job_id="mcf-1",
            source_title="Old Data Analyst",
            salary_min=5000,
            salary_max=7000,
        )
        newer = SourceListing(
            source="careers_gov",
            source_job_id="mcf-1",
            source_title="New Data Analyst",
            salary_min=6000,
            salary_max=8000,
        )
        session.add_all([older, newer])
        session.flush()
        session.add_all(
            [
                PostingObservation(source_listing=older),
                PostingObservation(source_listing=newer),
            ]
        )
        session.commit()

    with app.state.session_factory() as session:
        before = list_endpoint(
            limit=20,
            offset=0,
            status="pending",
            session=session,
        )
        response = dedupe_endpoint(session=session)

    assert before["data"]["source_listing_duplicate_groups"] == 1
    assert response["data"]["duplicate_groups_before"] == 1
    assert response["data"]["duplicate_groups_after"] == 0
    assert response["data"]["groups_merged"] == 1
    assert response["data"]["source_listings_removed"] == 1
    assert response["data"]["observations_moved"] == 1
    assert response["data"]["duplicate_candidates_created"] == 0

    with app.state.session_factory() as session:
        listings = session.scalars(select(SourceListing)).all()
        observations = session.scalars(select(PostingObservation)).all()

    assert len(listings) == 1
    assert listings[0].source == "careers_gov"
    assert listings[0].source_job_id == "mcf-1"
    assert listings[0].source_title == "New Data Analyst"
    assert listings[0].salary_min == 6000
    assert len(observations) == 2
    assert {observation.source_listing_id for observation in observations} == {
        listings[0].id
    }


def test_frontend_ingest_endpoint_accepts_mycareersfuture_alias(
    tmp_path, monkeypatch
) -> None:
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'server.sqlite3'}"))
    ingest_endpoint = _endpoint(app, "/api/v1/admin/ingest", method="POST")
    calls = []

    def fake_ingest_jobs(**kwargs):
        calls.append(kwargs)
        return IngestionResult(
            source=kwargs["source"],
            targets_seen=1,
            targets_ingested=1,
            targets_failed=0,
            jobs_seen=2,
            source_listings_upserted=2,
            observations_created=2,
            job_skills_extracted=1,
            duplicate_candidates=0,
        )

    monkeypatch.setattr("roleradar.app.server.ingest_jobs", fake_ingest_jobs)

    payload = ingest_endpoint(
        {
            "source": "mycareersfuture",
            "query": "AI engineer",
            "role_family": "ai_ml_engineer",
            "location": "Singapore",
        }
    )

    assert calls[0]["source"] == "careers_gov"
    assert calls[0]["query"] == "AI engineer"
    assert calls[0]["role_family_id"] == "ai_ml_engineer"
    assert payload["data"]["source"] == "careers_gov"
    assert payload["data"]["role_family"] == "ai_ml_engineer"
    assert payload["data"]["source_listings_upserted"] == 2
    assert payload["data"]["results"][0]["status"] == "completed"


def test_frontend_ingest_endpoint_accepts_custom_role_family(
    tmp_path, monkeypatch
) -> None:
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'server.sqlite3'}"))
    ingest_endpoint = _endpoint(app, "/api/v1/admin/ingest", method="POST")
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

    monkeypatch.setattr("roleradar.app.server.ingest_jobs", fake_ingest_jobs)

    payload = ingest_endpoint(
        {
            "source": "careers_gov",
            "query": "Data platform",
            "role_family": "custom:Data Platform",
            "location": "Singapore",
        }
    )

    assert calls[0]["role_family_id"] == "custom:data_platform"
    assert payload["data"]["role_family"] == "custom:data_platform"
    assert payload["data"]["role_family_label"] == "Data Platform"


def test_frontend_ingest_endpoint_normalizes_plain_custom_role_family(
    tmp_path, monkeypatch
) -> None:
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'server.sqlite3'}"))
    ingest_endpoint = _endpoint(app, "/api/v1/admin/ingest", method="POST")
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

    monkeypatch.setattr("roleradar.app.server.ingest_jobs", fake_ingest_jobs)

    payload = ingest_endpoint(
        {
            "source": "careers_gov",
            "query": "Data platform",
            "role_family": "Data Platform",
            "location": "Singapore",
        }
    )

    assert calls[0]["role_family_id"] == "custom:data_platform"
    assert payload["data"]["role_family"] == "custom:data_platform"
    assert payload["data"]["role_family_label"] == "Data Platform"


def test_role_family_endpoint_returns_canonical_role_summary(tmp_path) -> None:
    app = _seed_app(tmp_path)
    role_endpoint = _endpoint(app, "/api/v1/role-families")

    with app.state.session_factory() as session:
        payload = role_endpoint(
            days=30,
            limit=10,
            include_empty=False,
            session=session,
        )

    assert payload["data"]["items"][0]["id"] == "data_analyst"
    assert payload["data"]["items"][0]["label"] == "Data Analyst"
    assert payload["data"]["items"][0]["job_count"] == 1
    assert payload["data"]["items"][0]["top_skills"][0]["skill_name"] == "Python"


def _seed_app(tmp_path, *, duplicate: bool = False):
    database_url = f"sqlite:///{tmp_path / 'server.sqlite3'}"
    app = create_app(Settings(database_url=database_url))
    with app.state.session_factory() as session:
        skill_repo = SkillRepository(session)
        python = skill_repo.get_or_create_skill(name="Python")
        skill_repo.get_or_create_alias(skill=python, alias="Python")

        job_repo = JobRepository(session)
        company = job_repo.get_or_create_company(name="Example Pte Ltd")
        job = job_repo.get_or_create_job(
            title="Data Analyst",
            company=company,
            canonical_url="https://example.test/jobs/1",
            location="Singapore",
        description_text=(
            "Responsibilities Support data mapping between Salesforce and external "
            "systems. Required competencies and certifications Minimum 4 years of "
            "experience in data analysis. Preferred competencies and qualifications "
            "Interest or exposure to Salesforce."
        ),
        )
        skill_repo.add_job_skill(
            job=job,
            skill=python,
            extraction_method="test",
            confidence=1.0,
            matched_text="Python",
        )
        listing = job_repo.upsert_source_listing(
            source="lever",
            source_job_id="job-1",
            job=job,
            canonical_url="https://example.test/jobs/1",
            source_url="https://lever.test/job-1",
            source_company_name="Example Pte Ltd",
            source_title="Data Analyst",
            location="Singapore",
            description_text=(
                "Responsibilities Support data mapping between Salesforce and "
                "external systems. Required competencies and certifications Minimum "
                "4 years of experience in data analysis. Preferred competencies and "
                "qualifications Interest or exposure to Salesforce."
            ),
            salary_min=6000,
            salary_max=8000,
            salary_currency="SGD",
            salary_interval="monthly",
        )
        job_repo.record_observation(source_listing=listing)

        if duplicate:
            duplicate_job = job_repo.get_or_create_job(
                title="Data Analyst",
                company=company,
                canonical_url="https://example.test/jobs/2",
                location="Singapore",
                description_text="Python role",
            )
            duplicate_listing = job_repo.upsert_source_listing(
                source="greenhouse",
                source_job_id="job-2",
                job=duplicate_job,
                canonical_url="https://example.test/jobs/2",
                source_url="https://greenhouse.test/job-2",
                source_company_name="Example Pte Ltd",
                source_title="Data Analyst",
                location="Singapore",
                description_text="Python role",
            )
            job_repo.record_observation(source_listing=duplicate_listing)
            job_repo.record_duplicate_candidate(
                job=job,
                candidate_job=duplicate_job,
                match_type="company_title_location",
                score=0.95,
                reason="same company, title, and location",
            )

        session.commit()
    return app


def _create_legacy_source_listings_table(db_path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE source_listings (
                id INTEGER NOT NULL PRIMARY KEY,
                ingestion_run_id INTEGER,
                job_id INTEGER,
                source VARCHAR(64) NOT NULL,
                source_job_id VARCHAR(255) NOT NULL,
                canonical_url TEXT,
                source_url TEXT,
                source_company_name VARCHAR(255),
                source_title VARCHAR(500),
                location VARCHAR(255),
                workplace_type VARCHAR(64),
                description_text TEXT,
                text_quality VARCHAR(32),
                salary_min FLOAT,
                salary_max FLOAT,
                salary_currency VARCHAR(3),
                salary_interval VARCHAR(32),
                content_hash VARCHAR(128),
                raw_payload JSON,
                first_seen_at DATETIME,
                last_seen_at DATETIME,
                source_updated_at DATETIME
            )
            """
        )


def _endpoint(app, path: str, *, method: str = "GET"):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(
            route, "methods", set()
        ):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")
