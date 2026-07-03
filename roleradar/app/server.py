"""FastAPI web application for the RoleRadar local explorer."""

# ruff: noqa: B008

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from html import unescape
from io import StringIO
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from roleradar.analytics.salary_trends import (
    salary_coverage,
    salary_coverage_by_source,
    salary_range_summaries,
    top_salary_listings,
)
from roleradar.analytics.skill_trends import (
    skill_extraction_coverage_by_source,
    top_skills,
)
from roleradar.config.settings import Settings
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.models import (
    Company,
    DuplicateJobCandidate,
    IngestionRun,
    Job,
    JobSkill,
    Skill,
    SourceListing,
)
from roleradar.storage.repositories import JobRepository, normalize_text

VALID_JOB_SORTS = {
    "first_seen_at",
    "last_seen_at",
    "salary_midpoint",
    "title",
    "company",
}
VALID_ORDERS = {"asc", "desc"}
VALID_DUPLICATE_ACTIONS = {"merge", "dismiss", "keep_separate"}


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the local RoleRadar API and static frontend app."""
    settings = settings or Settings()
    engine = create_database_engine(
        settings.database_url,
        sqlite_wal=settings.sqlite_wal,
        sqlite_busy_timeout_ms=settings.sqlite_busy_timeout_ms,
    )
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    app = FastAPI(
        title="RoleRadar",
        version="0.1.0",
        description="Local Singapore labour-market intelligence explorer.",
    )
    app.state.settings = settings
    app.state.session_factory = session_factory

    def get_session() -> Iterable[Session]:
        with session_factory() as session:
            yield session

    @app.get("/api/v1/health")
    def health(session: Session = Depends(get_session)) -> dict[str, Any]:
        return {
            "status": "ok",
            "generated_at": _utc_now(),
            "database_url": settings.database_url,
            "total_records_in_db": _count(session, SourceListing),
        }

    @app.get("/api/v1/analytics/overview")
    def analytics_overview(
        days: int | None = Query(default=30, ge=1, le=366),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        coverage = salary_coverage(session, days=days)
        salary_summaries = salary_range_summaries(session, days=days)
        skill_rows = top_skills(session, days=days, limit=10)
        source_coverage = skill_extraction_coverage_by_source(session, days=days)
        recent_runs = _recent_ingestion_runs(session, limit=5)
        pending_duplicates = _count_duplicates(session, status="pending")
        total_listings = _count(session, SourceListing)
        data = {
            "kpis": {
                "canonical_jobs": _count(session, Job),
                "source_listings": total_listings,
                "companies": _count(session, Company),
                "skills": _count(session, Skill),
                "pending_duplicates": pending_duplicates,
                "salary_disclosure_rate": coverage.disclosure_rate,
            },
            "top_skills": [
                {"skill_name": row.skill_name, "job_count": row.job_count}
                for row in skill_rows
            ],
            "salary": {
                "coverage": _salary_coverage_payload(coverage),
                "by_source": [
                    _salary_coverage_payload(row)
                    for row in salary_coverage_by_source(session, days=days)
                ],
                "summaries": [
                    {
                        "currency": row.currency,
                        "interval": row.interval,
                        "posting_count": row.posting_count,
                        "closed_range_count": row.closed_range_count,
                        "min_salary": row.min_salary,
                        "max_salary": row.max_salary,
                        "average_midpoint": row.average_midpoint,
                        "average_annualized_midpoint": (
                            row.average_annualized_midpoint
                        ),
                    }
                    for row in salary_summaries
                ],
                "top_listings": [
                    {
                        "company_name": row.company_name,
                        "title": row.title,
                        "source": row.source,
                        "currency": row.currency,
                        "interval": row.interval,
                        "salary_min": row.salary_min,
                        "salary_max": row.salary_max,
                        "annualized_midpoint": row.annualized_midpoint,
                        "source_url": row.source_url,
                    }
                    for row in top_salary_listings(session, days=days, limit=10)
                ],
            },
            "skill_extraction_coverage": [
                {
                    "source": row.source,
                    "total_posting_count": row.total_posting_count,
                    "full_text_posting_count": row.full_text_posting_count,
                    "snippet_posting_count": row.snippet_posting_count,
                    "extracted_posting_count": row.extracted_posting_count,
                    "full_text_rate": row.full_text_rate,
                }
                for row in source_coverage
            ],
            "recent_ingestion_runs": recent_runs,
            "trend_caveat": (
                "Current snapshot only; growth is not reported until repeated "
                "observation windows exist."
            ),
        }
        return _wrapped(
            session,
            data,
            applied_filters={"days": days},
            sample_size=total_listings,
            missing_data_counts=_missing_counts(session),
        )

    @app.get("/api/v1/jobs")
    def list_jobs(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        sort_by: str = Query(default="last_seen_at"),
        order: str = Query(default="desc"),
        source: str | None = None,
        q: str | None = None,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        if sort_by not in VALID_JOB_SORTS:
            raise HTTPException(status_code=422, detail="Unsupported sort_by")
        if order not in VALID_ORDERS:
            raise HTTPException(status_code=422, detail="Unsupported order")

        listings = _filtered_source_listings(session, source=source, q=q)
        reverse = order == "desc"
        listings = sorted(
            listings,
            key=lambda listing: _job_sort_value(listing, sort_by),
            reverse=reverse,
        )
        page = listings[offset : offset + limit]
        data = {
            "total": len(listings),
            "limit": limit,
            "offset": offset,
            "items": [_source_listing_payload(listing) for listing in page],
        }
        return _wrapped(
            session,
            data,
            applied_filters={
                "source": source,
                "q": q,
                "limit": limit,
                "offset": offset,
                "sort_by": sort_by,
                "order": order,
            },
            sample_size=len(page),
            missing_data_counts=_missing_counts(session),
        )

    @app.get("/api/v1/jobs/export.csv")
    def export_jobs_csv(
        source: str | None = None,
        q: str | None = None,
        session: Session = Depends(get_session),
    ) -> Response:
        listings = sorted(
            _filtered_source_listings(session, source=source, q=q),
            key=lambda listing: listing.last_seen_at,
            reverse=True,
        )
        output = StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "job_id",
                "source_listing_id",
                "title",
                "company_name",
                "source",
                "source_job_id",
                "location",
                "workplace_type",
                "text_quality",
                "salary_min",
                "salary_max",
                "salary_currency",
                "salary_interval",
                "salary_midpoint",
                "source_url",
                "first_seen_at",
                "last_seen_at",
            ],
        )
        writer.writeheader()
        for listing in listings:
            writer.writerow(_source_listing_payload(listing))
        return Response(
            content=output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="roleradar-jobs.csv"'
            },
        )

    @app.get("/api/v1/jobs/{job_id}")
    def get_job(
        job_id: int,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        job = (
            session.execute(
            select(Job)
            .options(
                joinedload(Job.company),
                joinedload(Job.source_listings),
                joinedload(Job.job_skills).joinedload(JobSkill.skill),
            )
            .where(Job.id == job_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        data = _job_detail_payload(job)
        return _wrapped(
            session,
            data,
            applied_filters={"job_id": job_id},
            sample_size=len(job.source_listings),
        )

    @app.get("/api/v1/skills/{skill_id}")
    def get_skill(
        skill_id: int,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        skill = (
            session.execute(
            select(Skill)
            .options(joinedload(Skill.aliases), joinedload(Skill.job_skills))
            .where(Skill.id == skill_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if skill is None:
            raise HTTPException(status_code=404, detail="Skill not found")
        jobs = [
            job_skill.job
            for job_skill in skill.job_skills
            if job_skill.job is not None
        ]
        data = {
            "id": skill.id,
            "name": skill.name,
            "category": skill.category,
            "source_taxonomy": skill.source_taxonomy,
            "aliases": [
                {
                    "id": alias.id,
                    "alias": alias.alias,
                    "match_type": alias.match_type,
                    "case_sensitive": alias.case_sensitive,
                }
                for alias in skill.aliases
            ],
            "associated_postings": [_job_summary_payload(job) for job in jobs[:20]],
        }
        return _wrapped(
            session,
            data,
            applied_filters={"skill_id": skill_id},
            sample_size=len(jobs),
        )

    @app.get("/api/v1/roles/{role_id}")
    def get_role(
        role_id: str,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        keyword = normalize_text(role_id.replace("-", " "))
        jobs = [
            job
            for job in session.scalars(select(Job).options(joinedload(Job.company)))
            if keyword and keyword in job.normalized_title
        ]
        skill_counts: dict[str, int] = {}
        for job in jobs:
            for job_skill in job.job_skills:
                if job_skill.skill is None:
                    continue
                skill_counts[job_skill.skill.name] = (
                    skill_counts.get(job_skill.skill.name, 0) + 1
                )
        data = {
            "id": role_id,
            "label": role_id.replace("-", " ").title(),
            "match_type": "title_keyword",
            "job_count": len(jobs),
            "top_skills": [
                {"skill_name": skill_name, "job_count": count}
                for skill_name, count in sorted(
                    skill_counts.items(), key=lambda item: (-item[1], item[0])
                )[:10]
            ],
            "associated_postings": [_job_summary_payload(job) for job in jobs[:20]],
        }
        return _wrapped(
            session,
            data,
            applied_filters={"role_id": role_id},
            sample_size=len(jobs),
        )

    @app.get("/api/v1/companies/{company_id}")
    def get_company(
        company_id: int,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        company = (
            session.execute(
                select(Company)
                .options(joinedload(Company.jobs))
                .where(Company.id == company_id)
            )
            .unique()
            .scalar_one_or_none()
        )
        if company is None:
            raise HTTPException(status_code=404, detail="Company not found")
        data = {
            "id": company.id,
            "name": company.name,
            "industry": company.industry,
            "job_count": len(company.jobs),
            "jobs": [_job_summary_payload(job) for job in company.jobs[:50]],
        }
        return _wrapped(
            session,
            data,
            applied_filters={"company_id": company_id},
            sample_size=len(company.jobs),
        )

    @app.get("/api/v1/admin/runs")
    def list_ingestion_runs(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        rows = list(
            session.scalars(
                select(IngestionRun)
                .order_by(IngestionRun.started_at.desc(), IngestionRun.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        data = {
            "total": _count(session, IngestionRun),
            "limit": limit,
            "offset": offset,
            "items": [_ingestion_run_payload(row) for row in rows],
        }
        return _wrapped(session, data, sample_size=len(rows))

    @app.get("/api/v1/admin/duplicates")
    def list_duplicates(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        status: str | None = Query(default="pending"),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        repo = JobRepository(session)
        rows = repo.list_duplicate_candidates(
            status=status,
            limit=limit,
            offset=offset,
        )
        data = {
            "total": _count_duplicates(session, status=status),
            "limit": limit,
            "offset": offset,
            "items": [_duplicate_payload(row) for row in rows],
        }
        return _wrapped(
            session,
            data,
            applied_filters={"status": status, "limit": limit, "offset": offset},
            sample_size=len(rows),
        )

    @app.post("/api/v1/admin/duplicates/{duplicate_candidate_id}/resolve")
    def resolve_duplicate(
        duplicate_candidate_id: int,
        payload: dict[str, Any],
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        action = str(payload.get("action", ""))
        if action not in VALID_DUPLICATE_ACTIONS:
            raise HTTPException(status_code=422, detail="Unsupported action")
        repo = JobRepository(session)
        candidate = repo.get_duplicate_candidate(duplicate_candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="Duplicate candidate not found")
        expected_status = payload.get("expected_status")
        if expected_status and candidate.status != expected_status:
            raise HTTPException(status_code=409, detail="Duplicate candidate changed")
        audit_log = repo.resolve_duplicate_candidate(
            duplicate_candidate=candidate,
            action=action,
            actor=str(payload.get("actor") or "local-user"),
            reason=payload.get("reason"),
            payload=payload,
        )
        session.commit()
        data = {
            "duplicate_candidate": _duplicate_payload(candidate),
            "audit_log": {
                "id": audit_log.id,
                "action": audit_log.action,
                "previous_status": audit_log.previous_status,
                "new_status": audit_log.new_status,
                "created_at": _iso(audit_log.created_at),
            },
        }
        return _wrapped(session, data, sample_size=1)

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=static_dir / "assets"),
            name="assets",
        )

        @app.get("/")
        @app.get("/{path:path}")
        def frontend(path: str = "") -> FileResponse:
            requested = static_dir / path
            if path and requested.is_file():
                return FileResponse(requested)
            return FileResponse(static_dir / "index.html")

    return app


def run(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    reload: bool = False,
) -> None:
    """Run the local API and frontend server with uvicorn."""
    import uvicorn

    uvicorn.run(
        "roleradar.app.server:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
    )


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterable[Session]:
    """Provide a transactional session for small scripts/tests."""
    with session_factory() as session:
        yield session


def _wrapped(
    session: Session,
    data: Any,
    *,
    applied_filters: dict[str, Any] | None = None,
    sample_size: int | None = None,
    missing_data_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "meta": {
            "generated_at": _utc_now(),
            "applied_filters": applied_filters or {},
            "total_records_in_db": _count(session, SourceListing),
            "sample_size": sample_size,
            "missing_data_counts": missing_data_counts or {},
            "freshness_timestamp": _freshness_timestamp(session),
        },
        "data": data,
    }


def _filtered_source_listings(
    session: Session,
    *,
    source: str | None = None,
    q: str | None = None,
) -> list[SourceListing]:
    query = select(SourceListing).options(
        joinedload(SourceListing.job).joinedload(Job.company)
    )
    if source:
        query = query.where(SourceListing.source == source)
    listings = list(session.scalars(query).unique().all())
    if q:
        needle = normalize_text(q)
        listings = [
            listing
            for listing in listings
            if needle
            and (
                needle in normalize_text(listing.source_title or "")
                or needle in normalize_text(listing.source_company_name or "")
                or needle in normalize_text(listing.description_text or "")
            )
        ]
    return listings


def _source_listing_payload(listing: SourceListing) -> dict[str, Any]:
    job = listing.job
    company = job.company if job is not None else None
    return {
        "source_listing_id": listing.id,
        "job_id": job.id if job is not None else None,
        "title": job.title if job is not None else listing.source_title,
        "company_name": (
            company.name if company is not None else listing.source_company_name
        ),
        "source": listing.source,
        "source_job_id": listing.source_job_id,
        "location": listing.location or (job.location if job is not None else None),
        "workplace_type": listing.workplace_type,
        "text_quality": listing.text_quality,
        "salary_min": listing.salary_min,
        "salary_max": listing.salary_max,
        "salary_currency": listing.salary_currency,
        "salary_interval": listing.salary_interval,
        "salary_midpoint": _salary_midpoint(listing),
        "source_url": listing.source_url or listing.canonical_url,
        "first_seen_at": _iso(listing.first_seen_at),
        "last_seen_at": _iso(listing.last_seen_at),
    }


def _job_detail_payload(job: Job) -> dict[str, Any]:
    return {
        **_job_summary_payload(job),
        "description_text": _sanitize_text(job.description_text),
        "skills": [
            {
                "id": job_skill.skill.id,
                "name": job_skill.skill.name,
                "confidence": job_skill.confidence,
                "matched_text": job_skill.matched_text,
            }
            for job_skill in job.job_skills
            if job_skill.skill is not None
        ],
        "source_listings": [
            _source_listing_payload(listing) for listing in job.source_listings
        ],
    }


def _job_summary_payload(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "title": job.title,
        "company": {
            "id": job.company.id,
            "name": job.company.name,
        }
        if job.company is not None
        else None,
        "location": job.location,
        "canonical_url": job.canonical_url,
        "first_seen_at": _iso(job.first_seen_at),
        "last_seen_at": _iso(job.last_seen_at),
    }


def _duplicate_payload(candidate: DuplicateJobCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "job": _job_summary_payload(candidate.job),
        "candidate_job": _job_summary_payload(candidate.candidate_job),
        "match_type": candidate.match_type,
        "score": candidate.score,
        "reason": candidate.reason,
        "status": candidate.status,
        "created_at": _iso(candidate.created_at),
    }


def _ingestion_run_payload(run: IngestionRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "source": run.source,
        "status": run.status,
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
        "parameters": run.parameters,
        "error_message": run.error_message,
    }


def _salary_coverage_payload(row: Any) -> dict[str, Any]:
    return {
        "group": row.group,
        "total_posting_count": row.total_posting_count,
        "salary_posting_count": row.salary_posting_count,
        "disclosure_rate": row.disclosure_rate,
    }


def _recent_ingestion_runs(session: Session, *, limit: int) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(IngestionRun)
        .order_by(IngestionRun.started_at.desc(), IngestionRun.id.desc())
        .limit(limit)
    )
    return [_ingestion_run_payload(row) for row in rows]


def _job_sort_value(listing: SourceListing, sort_by: str) -> Any:
    if sort_by == "salary_midpoint":
        return _salary_midpoint(listing) or 0
    if sort_by == "title":
        return (
            listing.job.title
            if listing.job is not None
            else listing.source_title or ""
        )
    if sort_by == "company":
        if listing.job is not None and listing.job.company is not None:
            return listing.job.company.name
        return listing.source_company_name or ""
    return getattr(listing, sort_by)


def _salary_midpoint(listing: SourceListing) -> float | None:
    if listing.salary_min is None and listing.salary_max is None:
        return None
    if listing.salary_min is None:
        return listing.salary_max
    if listing.salary_max is None:
        return listing.salary_min
    return (listing.salary_min + listing.salary_max) / 2


def _missing_counts(session: Session) -> dict[str, int]:
    listings = list(session.scalars(select(SourceListing)).all())
    return {
        "salaries": sum(
            1
            for listing in listings
            if listing.salary_min is None and listing.salary_max is None
        ),
        "skills": sum(
            1
            for listing in listings
            if listing.job is not None and not listing.job.job_skills
        ),
    }


def _count(session: Session, model: type[Any]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _count_duplicates(session: Session, *, status: str | None = None) -> int:
    query = select(func.count()).select_from(DuplicateJobCandidate)
    if status:
        query = query.where(DuplicateJobCandidate.status == status)
    return int(session.scalar(query) or 0)


def _freshness_timestamp(session: Session) -> str | None:
    value = session.scalar(select(func.max(SourceListing.last_seen_at)))
    return _iso(value)


def _sanitize_text(value: str | None) -> str:
    if not value:
        return ""
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(without_tags)).strip()


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
