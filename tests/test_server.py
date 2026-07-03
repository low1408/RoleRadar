from __future__ import annotations

from sqlalchemy import select

from roleradar.app.server import create_app
from roleradar.config.settings import Settings
from roleradar.storage.models import DuplicateAuditLog
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
    assert "Current snapshot only" in payload["data"]["trend_caveat"]


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
            q=None,
            session=session,
        )

    assert payload["meta"]["sample_size"] == 1
    assert payload["data"]["total"] == 1
    assert payload["data"]["items"][0]["title"] == "Data Analyst"
    assert payload["data"]["items"][0]["salary_midpoint"] == 7000


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
            description_text="<p>Python and SQL role</p>",
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
            description_text="Python and SQL role",
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


def _endpoint(app, path: str, *, method: str = "GET"):
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(
            route, "methods", set()
        ):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")
