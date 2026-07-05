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
from types import SimpleNamespace
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload, sessionmaker

from roleradar.analytics.demand_signals import (
    active_listings_by_company,
    active_listings_by_company_and_role_family,
    active_listings_summary,
    company_hiring_breadth,
    new_listings_by_company,
)
from roleradar.analytics.role_intelligence import (
    canonical_role_family,
    canonical_role_family_by_id,
    custom_role_family_id,
    known_role_family_ids,
    role_family_catalog,
    role_family_detail,
    role_family_for_job,
    role_family_summaries,
    top_hiring_companies,
)
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
from roleradar.analytics.trend_engine import (
    company_hiring_velocity,
    posting_velocity,
    salary_trend_over_time,
    skill_demand_over_time,
    time_to_close,
)
from roleradar.config.settings import Settings
from roleradar.ingestion.fetch_jobs import ingest_jobs
from roleradar.ingestion.normalize_jobs import extract_job_description_sections
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.models import (
    Company,
    DeletedListing,
    DuplicateJobCandidate,
    IngestionRun,
    Job,
    JobSkill,
    PostingObservation,
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
FRONTEND_INGESTION_SOURCES = {"all", "adzuna", "careers_gov", "jobstreet"}
QUERY_INGESTION_SOURCES = ("careers_gov", "jobstreet", "adzuna")


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
        role_family: str | None = None,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        if role_family and not _is_supported_role_family_id(role_family):
            raise HTTPException(status_code=422, detail="Unsupported role_family")

        role_rows = role_family_summaries(session, days=days, limit=None)
        selected_role = (
            next((row for row in role_rows if row.id == role_family), None)
            if role_family
            else None
        )
        scoped_listings = (
            _filtered_source_listings(session, role_family=role_family)
            if role_family
            else []
        )
        coverage = (
            _salary_coverage_for_listings(
                selected_role.label if selected_role is not None else role_family,
                scoped_listings,
            )
            if role_family
            else salary_coverage(session, days=days)
        )
        salary_summaries = (
            [] if role_family else salary_range_summaries(session, days=days)
        )
        skill_rows = [] if role_family else top_skills(session, days=days, limit=10)
        company_rows = top_hiring_companies(
            session,
            days=days,
            family_id=role_family,
            limit=8,
        )
        source_coverage = (
            _skill_extraction_coverage_for_listings(scoped_listings)
            if role_family
            else skill_extraction_coverage_by_source(session, days=days)
        )
        recent_runs = _recent_ingestion_runs(session, limit=5)
        pending_duplicates = _count_duplicates(session, status="pending")
        total_listings = _count(session, SourceListing)
        demand_summary = active_listings_summary(session)
        demand_rows = active_listings_by_company(session, limit=10)
        scoped_skill_rows = (
            [
                {"skill_name": skill_name, "job_count": job_count}
                for skill_name, job_count in selected_role.top_skills
            ]
            if selected_role is not None
            else []
        )
        data = {
            "kpis": {
                "canonical_jobs": (
                    selected_role.job_count
                    if selected_role is not None
                    else _count_active_jobs(session)
                ),
                "source_listings": (
                    selected_role.source_listing_count
                    if selected_role is not None
                    else total_listings
                ),
                "companies": (
                    selected_role.company_count
                    if selected_role is not None
                    else _count(session, Company)
                ),
                "skills": (
                    len(selected_role.top_skills)
                    if selected_role is not None
                    else _count(session, Skill)
                ),
                "pending_duplicates": pending_duplicates,
                "salary_disclosure_rate": coverage.disclosure_rate,
                "active_listings": demand_summary.active_listing_count,
                "new_listings_7d": demand_summary.new_listing_count_7d,
                "new_listings_30d": demand_summary.new_listing_count_30d,
                "active_role_families": demand_summary.role_family_count,
            },
            "selected_role_family": (
                _role_family_payload(selected_role)
                if selected_role is not None
                else None
            ),
            "top_skills": scoped_skill_rows if role_family else [
                {"skill_name": row.skill_name, "job_count": row.job_count}
                for row in skill_rows
            ],
            "role_families": [
                _role_family_payload(row)
                for row in role_rows
            ],
            "top_hiring_companies": [
                _hiring_company_payload(row)
                for row in company_rows
            ],
            "company_demand_signals": [
                _company_demand_signal_payload(row) for row in demand_rows
            ],
            "salary": {
                "coverage": _salary_coverage_payload(coverage),
                "by_source": [
                    _salary_coverage_payload(row)
                    for row in (
                        _salary_coverage_by_source_for_listings(scoped_listings)
                        if role_family
                        else salary_coverage_by_source(session, days=days)
                    )
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
                        "p25_annualized_midpoint": row.p25_annualized_midpoint,
                        "median_annualized_midpoint": (
                            row.median_annualized_midpoint
                        ),
                        "p75_annualized_midpoint": row.p75_annualized_midpoint,
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
            applied_filters={"days": days, "role_family": role_family},
            sample_size=(
                selected_role.source_listing_count
                if selected_role is not None
                else total_listings
            ),
            missing_data_counts=_missing_counts(session),
        )

    @app.get("/api/v1/analytics/demand-signals")
    def analytics_demand_signals(
        days: int = Query(default=7, ge=1, le=366),
        limit: int = Query(default=10, ge=1, le=100),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        summary = active_listings_summary(session)
        data = {
            "summary": _active_listings_summary_payload(summary),
            "companies": [
                _company_demand_signal_payload(row)
                for row in active_listings_by_company(session, limit=limit)
            ],
            "company_role_families": [
                _company_role_family_demand_payload(row)
                for row in active_listings_by_company_and_role_family(
                    session,
                    limit=limit * 5,
                )
            ],
            "new_listings_by_company": [
                _new_listings_by_company_payload(row)
                for row in new_listings_by_company(
                    session,
                    days=days,
                    limit=limit,
                )
            ],
            "company_hiring_breadth": [
                _company_hiring_breadth_payload(row)
                for row in company_hiring_breadth(session, limit=limit)
            ],
            "caveat": (
                "New listings are counted from first_seen_at. "
                "Repeated observations are not counted as new listings."
            ),
        }
        return _wrapped(
            session,
            data,
            applied_filters={"days": days, "limit": limit},
            sample_size=len(data["companies"]),
            missing_data_counts=_missing_counts(session),
        )

    @app.get("/api/v1/analytics/trends")
    def analytics_trends(
        weeks: int = Query(default=12, ge=1, le=52),
        skill: str | None = None,
        role_family: str | None = None,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        if role_family and not _is_supported_role_family_id(role_family):
            raise HTTPException(status_code=422, detail="Unsupported role_family")

        selected_skill = _selected_trend_skill(
            session,
            skill=skill,
            role_family=role_family,
        )
        skill_rows = (
            skill_demand_over_time(
                session,
                skill_name=selected_skill,
                weeks=weeks,
            )
            if selected_skill
            else []
        )
        salary_rows = (
            salary_trend_over_time(
                session,
                family_id=role_family,
                weeks=weeks,
            )
            if role_family
            else []
        )
        velocity_rows = posting_velocity(
            session,
            family_id=role_family,
            weeks=weeks,
        )
        company_velocity_rows = company_hiring_velocity(
            session,
            family_id=role_family,
            weeks=weeks,
            limit=50,
        )
        close_stats = time_to_close(session, family_id=role_family)
        role_rows = role_family_summaries(session, days=None, limit=None)
        data = {
            "weeks": weeks,
            "selected_skill": selected_skill,
            "selected_role_family": _role_family_label(role_family),
            "selected_role_family_id": role_family,
            "available_role_families": [
                _role_family_payload(row) for row in role_rows
            ],
            "top_skills": [
                {"skill_name": row.skill_name, "job_count": row.job_count}
                for row in top_skills(session, days=None, limit=20)
            ],
            "skill_demand": [
                {
                    "week_start": row.week_start.isoformat(),
                    "count": row.count,
                    "previous_count": row.previous_count,
                    "delta": row.delta,
                    "delta_percent": row.delta_percent,
                }
                for row in skill_rows
            ],
            "salary_trend": [
                {
                    "week_start": row.week_start.isoformat(),
                    "posting_count": row.posting_count,
                    "average_annualized_midpoint": (
                        row.average_annualized_midpoint
                    ),
                }
                for row in salary_rows
            ],
            "posting_velocity": [
                {
                    "week_start": row.week_start.isoformat(),
                    "new_posting_count": row.new_posting_count,
                    "closed_posting_count": row.closed_posting_count,
                }
                for row in velocity_rows
            ],
            "company_hiring_velocity": [
                {
                    "week_start": row.week_start.isoformat(),
                    "company_id": row.company_id,
                    "company_name": row.company_name,
                    "new_posting_count": row.new_posting_count,
                }
                for row in company_velocity_rows
            ],
            "time_to_close": {
                "posting_count": close_stats.posting_count,
                "median_days": close_stats.median_days,
                "p75_days": close_stats.p75_days,
            },
            "caveat": (
                "Trend quality depends on repeated scheduled ingestion. "
                "Sparse observation history may produce flat or empty charts."
            ),
        }
        return _wrapped(
            session,
            data,
            applied_filters={
                "weeks": weeks,
                "skill": selected_skill,
                "role_family": role_family,
            },
            sample_size=len(velocity_rows),
            missing_data_counts=_missing_counts(session),
        )

    @app.get("/api/v1/analytics/trends/skills/{skill_name}")
    def skill_trend(
        skill_name: str,
        weeks: int = Query(default=12, ge=1, le=52),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        rows = skill_demand_over_time(
            session,
            skill_name=skill_name,
            weeks=weeks,
        )
        data = {
            "skill_name": skill_name,
            "weeks": weeks,
            "items": [
                {
                    "week_start": row.week_start.isoformat(),
                    "count": row.count,
                    "previous_count": row.previous_count,
                    "delta": row.delta,
                    "delta_percent": row.delta_percent,
                }
                for row in rows
            ],
        }
        return _wrapped(
            session,
            data,
            applied_filters={"skill_name": skill_name, "weeks": weeks},
            sample_size=len(rows),
        )

    @app.get("/api/v1/analytics/trends/salary/{family_id}")
    def salary_trend(
        family_id: str,
        weeks: int = Query(default=12, ge=1, le=52),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        if not _is_supported_role_family_id(family_id):
            raise HTTPException(status_code=404, detail="Role family not found")
        rows = salary_trend_over_time(
            session,
            family_id=family_id,
            weeks=weeks,
        )
        data = {
            "role_family": family_id,
            "role_family_label": _role_family_label(family_id),
            "weeks": weeks,
            "items": [
                {
                    "week_start": row.week_start.isoformat(),
                    "posting_count": row.posting_count,
                    "average_annualized_midpoint": row.average_annualized_midpoint,
                }
                for row in rows
            ],
        }
        return _wrapped(
            session,
            data,
            applied_filters={"family_id": family_id, "weeks": weeks},
            sample_size=len(rows),
        )

    @app.get("/api/v1/analytics/trends/velocity")
    def velocity_trend(
        weeks: int = Query(default=12, ge=1, le=52),
        role_family: str | None = None,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        if role_family and not _is_supported_role_family_id(role_family):
            raise HTTPException(status_code=422, detail="Unsupported role_family")
        rows = posting_velocity(
            session,
            family_id=role_family,
            weeks=weeks,
        )
        data = {
            "weeks": weeks,
            "role_family": role_family,
            "items": [
                {
                    "week_start": row.week_start.isoformat(),
                    "new_posting_count": row.new_posting_count,
                    "closed_posting_count": row.closed_posting_count,
                }
                for row in rows
            ],
        }
        return _wrapped(
            session,
            data,
            applied_filters={"weeks": weeks, "role_family": role_family},
            sample_size=len(rows),
        )

    @app.get("/api/v1/analytics/trends/company-velocity")
    def company_velocity_trend(
        weeks: int = Query(default=12, ge=1, le=52),
        role_family: str | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        if role_family and not _is_supported_role_family_id(role_family):
            raise HTTPException(status_code=422, detail="Unsupported role_family")
        rows = company_hiring_velocity(
            session,
            family_id=role_family,
            weeks=weeks,
            limit=limit,
        )
        data = {
            "weeks": weeks,
            "role_family": role_family,
            "items": [
                {
                    "week_start": row.week_start.isoformat(),
                    "company_id": row.company_id,
                    "company_name": row.company_name,
                    "new_posting_count": row.new_posting_count,
                }
                for row in rows
            ],
        }
        return _wrapped(
            session,
            data,
            applied_filters={
                "weeks": weeks,
                "role_family": role_family,
                "limit": limit,
            },
            sample_size=len(rows),
        )

    @app.get("/api/v1/jobs")
    def list_jobs(
        limit: int = Query(default=20, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        sort_by: str = Query(default="last_seen_at"),
        order: str = Query(default="desc"),
        source: str | None = None,
        role_family: str | None = None,
        q: str | None = None,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        if sort_by not in VALID_JOB_SORTS:
            raise HTTPException(status_code=422, detail="Unsupported sort_by")
        if order not in VALID_ORDERS:
            raise HTTPException(status_code=422, detail="Unsupported order")
        if role_family and not _is_supported_role_family_id(role_family):
            raise HTTPException(status_code=422, detail="Unsupported role_family")

        listings = _filtered_source_listings(
            session,
            source=source,
            role_family=role_family,
            q=q,
        )
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
                "role_family": role_family,
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
        role_family: str | None = None,
        q: str | None = None,
        session: Session = Depends(get_session),
    ) -> Response:
        if role_family and not _is_supported_role_family_id(role_family):
            raise HTTPException(status_code=422, detail="Unsupported role_family")
        listings = sorted(
            _filtered_source_listings(
                session,
                source=source,
                role_family=role_family,
                q=q,
            ),
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
                "role_family",
                "source_job_id",
                "location",
                "workplace_type",
                "text_quality",
                "salary_min",
                "salary_max",
                "salary_currency",
                "salary_interval",
                "salary_midpoint",
                "responsibilities",
                "required_competencies_and_certifications",
                "preferred_competencies_and_qualifications",
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

    @app.delete("/api/v1/jobs/{source_listing_id}")
    def delete_job_listing(
        source_listing_id: int,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        listing = session.scalar(
            select(SourceListing).where(SourceListing.id == source_listing_id)
        )
        if listing is None:
            raise HTTPException(status_code=404, detail="Source listing not found")

        _cleanup_old_deleted_listings(session)

        repo = JobRepository(session)
        repo.delete_source_listing(listing)
        session.commit()
        return {"status": "ok", "deleted_source_listing_id": source_listing_id}

    @app.post("/api/v1/jobs/{source_listing_id}/restore")
    def restore_job_listing(
        source_listing_id: int,
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        repo = JobRepository(session)
        try:
            repo.restore_source_listing(source_listing_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        session.commit()
        return {"status": "ok", "restored_source_listing_id": source_listing_id}

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

    @app.get("/api/v1/role-families")
    def list_role_families(
        days: int | None = Query(default=30, ge=1, le=366),
        limit: int = Query(default=20, ge=1, le=100),
        include_empty: bool = Query(default=False),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        if include_empty:
            summary_rows = role_family_summaries(session, days=days, limit=None)
            summary_by_id = {row.id: row for row in summary_rows}
            catalog_rows = [
                summary_by_id.get(role.id) or _empty_role_family_summary(role)
                for role in role_family_catalog()
            ]
            catalog_ids = {role.id for role in role_family_catalog()}
            custom_rows = [row for row in summary_rows if row.id not in catalog_ids]
            rows = (catalog_rows + custom_rows)[:limit]
        else:
            rows = role_family_summaries(session, days=days, limit=limit)
        data = {
            "total": len(rows),
            "items": [_role_family_payload(row) for row in rows],
        }
        return _wrapped(
            session,
            data,
            applied_filters={
                "days": days,
                "limit": limit,
                "include_empty": include_empty,
            },
            sample_size=len(rows),
        )

    @app.get("/api/v1/role-families/{family_id}")
    def get_role_family(
        family_id: str,
        days: int | None = Query(default=30, ge=1, le=366),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        if not _is_supported_role_family_id(family_id):
            raise HTTPException(status_code=404, detail="Role family not found")
        row = role_family_detail(session, family_id=family_id, days=days)
        if row is None:
            raise HTTPException(status_code=404, detail="Role family not found")
        return _wrapped(
            session,
            _role_family_payload(row),
            applied_filters={"family_id": family_id, "days": days},
            sample_size=row.job_count,
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

    @app.post("/api/v1/admin/ingest")
    def ingest_from_frontend(payload: dict[str, Any]) -> dict[str, Any]:
        source = _source_from_frontend_payload(payload.get("source"))
        query = _non_empty_string(payload.get("query"))
        role_family_id = _role_family_from_frontend_payload(
            payload.get("role_family")
        )
        location = _non_empty_string(payload.get("location"))
        country = _non_empty_string(payload.get("country")) or "sg"
        results_per_page = _bounded_int(
            payload.get("results_per_page"),
            default=20,
            minimum=1,
            maximum=100,
            field_name="results_per_page",
        )
        max_pages = _bounded_int(
            payload.get("max_pages"),
            default=1,
            minimum=1,
            maximum=10,
            field_name="max_pages",
        )

        if not query:
            raise HTTPException(status_code=422, detail="query is required")

        sources = QUERY_INGESTION_SOURCES if source == "all" else (source,)
        results = [
            _run_frontend_ingestion(
                settings=settings,
                source=ingestion_source,
                query=query,
                role_family_id=role_family_id,
                location=location,
                country=country,
                results_per_page=results_per_page,
                max_pages=max_pages,
            )
            for ingestion_source in sources
        ]
        jobs_seen = sum(result["jobs_seen"] for result in results)
        source_listings = sum(result["source_listings_upserted"] for result in results)
        data = {
            "source": source,
            "query": query,
            "role_family": role_family_id,
            "role_family_label": _role_family_label(role_family_id),
            "location": location,
            "results_per_page": results_per_page,
            "max_pages": max_pages,
            "jobs_seen": jobs_seen,
            "source_listings_upserted": source_listings,
            "results": results,
        }
        with session_factory() as read_session:
            return _wrapped(
                read_session,
                data,
                applied_filters={
                "source": source,
                "query": query,
                "role_family": role_family_id,
                "location": location,
                    "country": country,
                    "results_per_page": results_per_page,
                    "max_pages": max_pages,
                },
                sample_size=source_listings,
            )

    @app.get("/api/v1/admin/deleted-listings")
    def list_deleted_listings(
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        _cleanup_old_deleted_listings(session)
        session.commit()

        rows = session.scalars(
            select(DeletedListing).order_by(DeletedListing.deleted_at.desc())
        ).all()
        data = {
            "items": [
                {
                    "id": row.id,
                    "source_listing_id": row.source_listing_id,
                    "deleted_at": _iso(row.deleted_at),
                    "title": row.payload["source_listing"]["source_title"],
                    "company_name": row.payload["source_listing"]["source_company_name"],
                    "source": row.payload["source_listing"]["source"],
                }
                for row in rows
            ]
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
            "source_listing_duplicate_groups": (
                _count_source_listing_duplicate_groups(session)
            ),
            "field_duplicate_listing_groups": (
                _count_field_equivalent_source_listing_duplicate_groups(session)
            ),
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

    @app.post("/api/v1/admin/source-listings/dedupe")
    def dedupe_source_listings(
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        data = _deduplicate_source_listings(session)
        data.update(_scan_duplicate_job_candidates(session))
        session.commit()
        return _wrapped(
            session,
            data,
            sample_size=(
                data["source_listings_removed"]
                + data["duplicate_candidates_created"]
                + data["duplicate_candidates_refreshed"]
            ),
        )

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

    @app.on_event("startup")
    def startup_cleanup() -> None:
        with session_factory() as session:
            _cleanup_old_deleted_listings(session)
            session.commit()

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


def _source_from_frontend_payload(value: Any) -> str:
    source = str(value or "").strip().casefold()
    if source == "mycareersfuture":
        source = "careers_gov"
    if source not in FRONTEND_INGESTION_SOURCES:
        raise HTTPException(status_code=422, detail="Unsupported source")
    return source


def _non_empty_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _role_family_from_frontend_payload(value: Any) -> str:
    role_family_id = _non_empty_string(value)
    if role_family_id is None:
        raise HTTPException(status_code=422, detail="role_family required")
    if canonical_role_family_by_id(role_family_id) is not None:
        return role_family_id

    custom_label = (
        role_family_id.removeprefix("custom:")
        if role_family_id.startswith("custom:")
        else role_family_id
    )
    custom_id = custom_role_family_id(custom_label)
    if custom_id is None:
        raise HTTPException(status_code=422, detail="Unsupported role_family")
    return custom_id


def _is_supported_role_family_id(role_family_id: str) -> bool:
    return (
        role_family_id in known_role_family_ids()
        or canonical_role_family_by_id(role_family_id) is not None
    )


def _role_family_label(role_family_id: str | None) -> str | None:
    role = canonical_role_family_by_id(role_family_id)
    return role.label if role is not None else None


def _selected_trend_skill(
    session: Session,
    *,
    skill: str | None,
    role_family: str | None,
) -> str | None:
    explicit_skill = _non_empty_string(skill)
    if explicit_skill is not None:
        return explicit_skill

    if role_family:
        role_row = role_family_detail(session, family_id=role_family, days=None)
        if role_row is not None and role_row.top_skills:
            return role_row.top_skills[0][0]

    top_skill = next(iter(top_skills(session, days=None, limit=1)), None)
    return top_skill.skill_name if top_skill is not None else None


def _bounded_int(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
    field_name: str,
) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be an integer",
        ) from exc
    if parsed < minimum or parsed > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be between {minimum} and {maximum}",
        )
    return parsed


def _run_frontend_ingestion(
    *,
    settings: Settings,
    source: str,
    query: str,
    role_family_id: str,
    location: str | None,
    country: str,
    results_per_page: int,
    max_pages: int,
) -> dict[str, Any]:
    if source == "adzuna" and not (
        settings.adzuna_app_id and settings.adzuna_app_key
    ):
        return _frontend_ingestion_result(
            source=source,
            status="skipped",
            role_family_id=role_family_id,
            error_message="Adzuna credentials are not configured.",
        )
    if source in {"adzuna", "jobstreet"} and not location:
        return _frontend_ingestion_result(
            source=source,
            status="skipped",
            role_family_id=role_family_id,
            error_message=f"{source} ingestion requires a location.",
        )
    try:
        result = ingest_jobs(
            database_url=settings.database_url,
            source=source,
            query=query,
            role_family_id=role_family_id,
            location=location,
            country=country,
            results_per_page=results_per_page,
            max_pages=max_pages,
            adzuna_app_id=settings.adzuna_app_id,
            adzuna_app_key=settings.adzuna_app_key,
            careers_gov_timeout_seconds=settings.careers_gov_timeout_seconds,
            careers_gov_throttle_seconds=settings.careers_gov_throttle_seconds,
            jobstreet_site_key=settings.jobstreet_site_key,
            jobstreet_timeout_seconds=settings.jobstreet_timeout_seconds,
            sqlite_wal=settings.sqlite_wal,
            sqlite_busy_timeout_ms=settings.sqlite_busy_timeout_ms,
        )
    except ValueError as exc:
        return _frontend_ingestion_result(
            source=source,
            status="skipped",
            role_family_id=role_family_id,
            error_message=str(exc),
        )

    status = "completed_with_errors" if result.error_message else "completed"
    return _frontend_ingestion_result(
        source=source,
        status=status,
        role_family_id=role_family_id,
        targets_seen=result.targets_seen,
        targets_ingested=result.targets_ingested,
        targets_failed=result.targets_failed,
        jobs_seen=result.jobs_seen,
        source_listings_upserted=result.source_listings_upserted,
        observations_created=result.observations_created,
        job_skills_extracted=result.job_skills_extracted,
        duplicate_candidates=result.duplicate_candidates,
        error_message=result.error_message,
    )


def _frontend_ingestion_result(
    *,
    source: str,
    status: str,
    role_family_id: str | None = None,
    targets_seen: int = 0,
    targets_ingested: int = 0,
    targets_failed: int = 0,
    jobs_seen: int = 0,
    source_listings_upserted: int = 0,
    observations_created: int = 0,
    job_skills_extracted: int = 0,
    duplicate_candidates: int = 0,
    error_message: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "status": status,
        "role_family": role_family_id,
        "targets_seen": targets_seen,
        "targets_ingested": targets_ingested,
        "targets_failed": targets_failed,
        "jobs_seen": jobs_seen,
        "source_listings_upserted": source_listings_upserted,
        "observations_created": observations_created,
        "job_skills_extracted": job_skills_extracted,
        "duplicate_candidates": duplicate_candidates,
        "error_message": error_message,
    }


def _cleanup_old_deleted_listings(session: Session) -> None:
    from datetime import timedelta
    cutoff = datetime.now(UTC) - timedelta(days=2)
    old_listings = session.scalars(
        select(DeletedListing).where(DeletedListing.deleted_at < cutoff)
    ).all()
    for row in old_listings:
        session.delete(row)


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


def _count_source_listing_duplicate_groups(session: Session) -> int:
    rows = session.execute(
        select(SourceListing.source, SourceListing.source_job_id)
        .group_by(SourceListing.source, SourceListing.source_job_id)
        .having(func.count(SourceListing.id) > 1)
    ).all()
    return len(rows)


def _count_field_equivalent_source_listing_duplicate_groups(session: Session) -> int:
    return len(
        [
            listings
            for listings in _field_equivalent_source_listing_groups(session).values()
            if len(listings) > 1
        ]
    )


def _deduplicate_source_listings(session: Session) -> dict[str, Any]:
    duplicate_groups_before = _count_source_listing_duplicate_groups(session)
    field_duplicate_groups_before = (
        _count_field_equivalent_source_listing_duplicate_groups(session)
    )
    groups: dict[tuple[str, str], list[SourceListing]] = {}
    listings = session.scalars(
        select(SourceListing).order_by(
            SourceListing.source.asc(),
            SourceListing.source_job_id.asc(),
            SourceListing.last_seen_at.desc(),
            SourceListing.id.desc(),
        )
    ).all()
    for listing in listings:
        groups.setdefault((listing.source, listing.source_job_id), []).append(listing)

    groups_merged = 0
    field_groups_merged = 0
    source_listings_removed = 0
    observations_moved = 0
    redundant_jobs_closed = 0

    for duplicate_listings in groups.values():
        if len(duplicate_listings) < 2:
            continue
        groups_merged += 1
        group_result = _merge_source_listing_duplicate_group(
            session,
            duplicate_listings,
        )
        source_listings_removed += group_result["source_listings_removed"]
        observations_moved += group_result["observations_moved"]
        redundant_jobs_closed += group_result["redundant_jobs_closed"]

    session.flush()

    for duplicate_listings in _field_equivalent_source_listing_groups(
        session
    ).values():
        if len(duplicate_listings) < 2:
            continue
        group_result = _merge_source_listing_duplicate_group(
            session,
            duplicate_listings,
        )
        if group_result["source_listings_removed"]:
            field_groups_merged += 1
        source_listings_removed += group_result["source_listings_removed"]
        observations_moved += group_result["observations_moved"]
        redundant_jobs_closed += group_result["redundant_jobs_closed"]

    session.flush()
    return {
        "duplicate_groups_before": duplicate_groups_before,
        "duplicate_groups_after": _count_source_listing_duplicate_groups(session),
        "field_duplicate_groups_before": field_duplicate_groups_before,
        "field_duplicate_groups_after": (
            _count_field_equivalent_source_listing_duplicate_groups(session)
        ),
        "groups_merged": groups_merged,
        "field_groups_merged": field_groups_merged,
        "source_listings_removed": source_listings_removed,
        "observations_moved": observations_moved,
        "redundant_jobs_closed": redundant_jobs_closed,
    }


def _merge_source_listing_duplicate_group(
    session: Session,
    duplicate_listings: list[SourceListing],
) -> dict[str, int]:
    keeper = duplicate_listings[0]
    redundant_listings = duplicate_listings[1:]
    redundant_listing_ids = {
        listing.id for listing in redundant_listings if listing.id is not None
    }
    affected_jobs = {
        listing.job for listing in redundant_listings if listing.job is not None
    }
    source_listings_removed = 0
    observations_moved = 0
    redundant_jobs_closed = 0

    for redundant in redundant_listings:
        if redundant.first_seen_at and (
            keeper.first_seen_at is None
            or redundant.first_seen_at < keeper.first_seen_at
        ):
            keeper.first_seen_at = redundant.first_seen_at
        if redundant.last_seen_at and (
            keeper.last_seen_at is None
            or redundant.last_seen_at > keeper.last_seen_at
        ):
            keeper.last_seen_at = redundant.last_seen_at
        if keeper.job is not None and redundant.job is not None:
            _preserve_job_seen_window(keeper.job, redundant.job)

        observations = session.scalars(
            select(PostingObservation).where(
                PostingObservation.source_listing_id == redundant.id
            )
        ).all()
        for observation in observations:
            observation.source_listing = keeper
            observations_moved += 1

        session.delete(redundant)
        source_listings_removed += 1

    now = datetime.now(UTC)
    keeper_job_id = keeper.job.id if keeper.job is not None else None
    for job in affected_jobs:
        if job is None or job.id is None or job.id == keeper_job_id:
            continue
        remaining_listings = [
            listing
            for listing in job.source_listings
            if listing.id not in redundant_listing_ids
        ]
        if not remaining_listings and job.closed_at is None:
            job.closed_at = now
            redundant_jobs_closed += 1

    return {
        "source_listings_removed": source_listings_removed,
        "observations_moved": observations_moved,
        "redundant_jobs_closed": redundant_jobs_closed,
    }


def _preserve_job_seen_window(keeper: Job, redundant: Job) -> None:
    if redundant.first_seen_at and (
        keeper.first_seen_at is None or redundant.first_seen_at < keeper.first_seen_at
    ):
        keeper.first_seen_at = redundant.first_seen_at
    if redundant.last_seen_at and (
        keeper.last_seen_at is None or redundant.last_seen_at > keeper.last_seen_at
    ):
        keeper.last_seen_at = redundant.last_seen_at


def _field_equivalent_source_listing_groups(
    session: Session,
) -> dict[tuple[Any, ...], list[SourceListing]]:
    groups: dict[tuple[Any, ...], list[SourceListing]] = {}
    listings = session.scalars(
        select(SourceListing)
        .options(joinedload(SourceListing.job).joinedload(Job.company))
        .order_by(
            SourceListing.source.asc(),
            SourceListing.last_seen_at.desc(),
            SourceListing.id.desc(),
        )
    ).unique().all()
    for listing in listings:
        key = _field_equivalent_source_listing_key(listing)
        if key is None:
            continue
        groups.setdefault(key, []).append(listing)
    return groups


def _field_equivalent_source_listing_key(
    listing: SourceListing,
) -> tuple[Any, ...] | None:
    job = listing.job
    company_name = listing.source_company_name
    if not company_name and job is not None and job.company is not None:
        company_name = job.company.name
    title = listing.source_title or (job.title if job is not None else None)
    location = listing.location or (job.location if job is not None else None)
    company_key = normalize_text(company_name or "")
    title_key = normalize_text(title or "")
    location_key = normalize_text(location or "")
    if not listing.source or not company_key or not title_key:
        return None

    content_signal = _field_duplicate_content_signal(listing)
    if content_signal is None:
        return None

    return (
        listing.source,
        company_key,
        title_key,
        location_key,
        _salary_duplicate_key(listing),
        content_signal,
    )


def _field_duplicate_content_signal(listing: SourceListing) -> tuple[str, Any] | None:
    if listing.content_hash:
        return ("content_hash", listing.content_hash)

    sections = _structured_sections_for_listing(listing)
    section_values = tuple(
        normalize_text(sections.get(field_name, ""))
        for field_name in (
            "responsibilities",
            "required_competencies_and_certifications",
            "preferred_competencies_and_qualifications",
        )
    )
    substantive_sections = [
        value for value in section_values if len(value) >= 20
    ]
    if len(substantive_sections) >= 2:
        return ("structured_sections", section_values)
    return None


def _salary_duplicate_key(listing: SourceListing) -> tuple[Any, ...]:
    return (
        _rounded_salary_value(listing.salary_min),
        _rounded_salary_value(listing.salary_max),
        normalize_text(listing.salary_currency or ""),
        normalize_text(listing.salary_interval or ""),
    )


def _rounded_salary_value(value: float | None) -> float | None:
    return round(float(value), 2) if value is not None else None


def _scan_duplicate_job_candidates(session: Session) -> dict[str, Any]:
    repo = JobRepository(session)
    active_jobs = list(
        session.scalars(
            select(Job)
            .where(Job.closed_at.is_(None))
            .order_by(Job.id.asc())
        ).all()
    )
    seen_pairs: set[tuple[int, int]] = set()
    candidates_created = 0
    candidates_refreshed = 0

    for job in active_jobs:
        if job.id is None:
            continue
        for match in repo.find_duplicate_candidate_matches(job):
            candidate_job = match.candidate_job
            if candidate_job.id is None:
                continue
            first_job, second_job = sorted(
                [job, candidate_job],
                key=lambda item: item.id,
            )
            pair = (first_job.id, second_job.id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            existing = session.scalar(
                select(DuplicateJobCandidate).where(
                    DuplicateJobCandidate.job_id == first_job.id,
                    DuplicateJobCandidate.candidate_job_id == second_job.id,
                )
            )
            repo.record_duplicate_candidate(
                job=job,
                candidate_job=candidate_job,
                match_type=match.match_type,
                score=match.score,
                reason=match.reason,
            )
            if existing is None:
                candidates_created += 1
            else:
                candidates_refreshed += 1

    session.flush()
    return {
        "jobs_scanned": len(active_jobs),
        "duplicate_candidate_pairs_found": len(seen_pairs),
        "duplicate_candidates_created": candidates_created,
        "duplicate_candidates_refreshed": candidates_refreshed,
        "pending_duplicate_candidates_after": _count_duplicates(
            session,
            status="pending",
        ),
    }


def _filtered_source_listings(
    session: Session,
    *,
    source: str | None = None,
    role_family: str | None = None,
    q: str | None = None,
) -> list[SourceListing]:
    query = select(SourceListing).options(
        joinedload(SourceListing.job).joinedload(Job.company)
    )
    if source:
        query = query.where(SourceListing.source == source)
    listings = list(session.scalars(query).unique().all())
    if role_family:
        listings = [
            listing
            for listing in listings
            if _role_family_for_listing(listing)["id"] == role_family
        ]
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
    structured_sections = _structured_sections_for_listing(listing)
    role_family = _role_family_for_listing(listing)
    return {
        "source_listing_id": listing.id,
        "job_id": job.id if job is not None else None,
        "title": job.title if job is not None else listing.source_title,
        "company_name": (
            company.name if company is not None else listing.source_company_name
        ),
        "source": listing.source,
        "role_family": role_family,
        "source_job_id": listing.source_job_id,
        "location": listing.location or (job.location if job is not None else None),
        "workplace_type": listing.workplace_type,
        "text_quality": listing.text_quality,
        "salary_min": listing.salary_min,
        "salary_max": listing.salary_max,
        "salary_currency": listing.salary_currency,
        "salary_interval": listing.salary_interval,
        "salary_midpoint": _salary_midpoint(listing),
        "responsibilities": structured_sections.get("responsibilities"),
        "required_competencies_and_certifications": structured_sections.get(
            "required_competencies_and_certifications"
        ),
        "preferred_competencies_and_qualifications": structured_sections.get(
            "preferred_competencies_and_qualifications"
        ),
        "source_url": listing.source_url or listing.canonical_url,
        "first_seen_at": _iso(listing.first_seen_at),
        "last_seen_at": _iso(listing.last_seen_at),
    }


def _job_detail_payload(job: Job) -> dict[str, Any]:
    structured_sections = extract_job_description_sections(job.description_text)
    return {
        **_job_summary_payload(job),
        "description_text": _sanitize_text(job.description_text),
        "responsibilities": structured_sections.get("responsibilities"),
        "required_competencies_and_certifications": structured_sections.get(
            "required_competencies_and_certifications"
        ),
        "preferred_competencies_and_qualifications": structured_sections.get(
            "preferred_competencies_and_qualifications"
        ),
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
    role = role_family_for_job(job)
    return {
        "id": job.id,
        "title": job.title,
        "role_family": {
            "id": role.id,
            "label": role.label,
            "confidence": role.confidence,
            "matched_phrase": role.matched_phrase,
        },
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


def _active_listings_summary_payload(row: Any) -> dict[str, Any]:
    return {
        "active_listing_count": row.active_listing_count,
        "new_listing_count_7d": row.new_listing_count_7d,
        "new_listing_count_30d": row.new_listing_count_30d,
        "company_count": row.company_count,
        "role_family_count": row.role_family_count,
    }


def _company_demand_signal_payload(row: Any) -> dict[str, Any]:
    return {
        "company_name": row.company_name,
        "active_listing_count": row.active_listing_count,
        "new_listing_count_7d": row.new_listing_count_7d,
        "new_listing_count_30d": row.new_listing_count_30d,
        "previous_new_listing_count_7d": row.previous_new_listing_count_7d,
        "week_over_week_new_listing_delta": row.week_over_week_new_listing_delta,
        "role_family_count": row.role_family_count,
        "top_role_families": [
            {"role_family": role_family, "listing_count": listing_count}
            for role_family, listing_count in row.top_role_families
        ],
        "salary_disclosure_rate": row.salary_disclosure_rate,
    }


def _company_role_family_demand_payload(row: Any) -> dict[str, Any]:
    return {
        "company_name": row.company_name,
        "role_family_id": row.role_family_id,
        "role_family_label": row.role_family_label,
        "active_listing_count": row.active_listing_count,
    }


def _new_listings_by_company_payload(row: Any) -> dict[str, Any]:
    return {
        "company_name": row.company_name,
        "new_listing_count": row.new_listing_count,
    }


def _company_hiring_breadth_payload(row: Any) -> dict[str, Any]:
    return {
        "company_name": row.company_name,
        "role_family_count": row.role_family_count,
    }


def _salary_coverage_for_listings(
    group: str | None,
    listings: list[SourceListing],
) -> Any:
    salary_count = sum(1 for listing in listings if _has_salary(listing))
    total_count = len(listings)
    return SimpleNamespace(
        group=group or "selected role family",
        total_posting_count=total_count,
        salary_posting_count=salary_count,
        disclosure_rate=salary_count / total_count if total_count else 0.0,
    )


def _salary_coverage_by_source_for_listings(
    listings: list[SourceListing],
) -> list[Any]:
    grouped: dict[str, list[SourceListing]] = {}
    for listing in listings:
        grouped.setdefault(listing.source, []).append(listing)
    return [
        _salary_coverage_for_listings(source, source_listings)
        for source, source_listings in sorted(grouped.items())
    ]


def _skill_extraction_coverage_for_listings(
    listings: list[SourceListing],
) -> list[dict[str, Any]]:
    grouped: dict[str, list[SourceListing]] = {}
    for listing in listings:
        grouped.setdefault(listing.source, []).append(listing)
    rows = []
    for source, source_listings in sorted(grouped.items()):
        total_count = len(source_listings)
        full_text_count = sum(
            1 for listing in source_listings if listing.text_quality == "full_text"
        )
        snippet_count = sum(
            1 for listing in source_listings if listing.text_quality == "snippet"
        )
        extracted_count = sum(
            1
            for listing in source_listings
            if listing.job is not None and bool(listing.job.job_skills)
        )
        rows.append(
            SimpleNamespace(
                source=source,
                total_posting_count=total_count,
                full_text_posting_count=full_text_count,
                snippet_posting_count=snippet_count,
                extracted_posting_count=extracted_count,
                full_text_rate=full_text_count / total_count if total_count else 0.0,
            )
        )
    return rows


def _has_salary(listing: SourceListing) -> bool:
    return listing.salary_min is not None or listing.salary_max is not None


def _role_family_payload(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "label": row.label,
        "job_count": row.job_count,
        "source_listing_count": row.source_listing_count,
        "company_count": row.company_count,
        "salary_listing_count": row.salary_listing_count,
        "average_annualized_salary": row.average_annualized_salary,
        "top_sources": [
            {"source": source, "posting_count": posting_count}
            for source, posting_count in row.top_sources
        ],
        "top_skills": [
            {"skill_name": skill_name, "job_count": job_count}
            for skill_name, job_count in row.top_skills
        ],
        "example_titles": list(row.example_titles),
    }


def _empty_role_family_summary(role: Any) -> Any:
    return SimpleNamespace(
        id=role.id,
        label=role.label,
        job_count=0,
        source_listing_count=0,
        company_count=0,
        salary_listing_count=0,
        average_annualized_salary=None,
        top_sources=(),
        top_skills=(),
        example_titles=(),
    )


def _hiring_company_payload(row: Any) -> dict[str, Any]:
    return {
        "company_name": row.company_name,
        "job_count": row.job_count,
        "source_listing_count": row.source_listing_count,
        "latest_seen_at": _iso(row.latest_seen_at),
        "top_role_families": [
            {"role_family": role_family, "job_count": job_count}
            for role_family, job_count in row.top_role_families
        ],
        "top_sources": [
            {"source": source, "posting_count": posting_count}
            for source, posting_count in row.top_sources
        ],
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


def _structured_sections_for_listing(listing: SourceListing) -> dict[str, str]:
    raw_payload = listing.raw_payload if isinstance(listing.raw_payload, dict) else {}
    raw_sections = raw_payload.get("structured_sections")
    if isinstance(raw_sections, dict):
        return {
            str(key): str(value)
            for key, value in raw_sections.items()
            if value is not None
        }
    return extract_job_description_sections(listing.description_text)


def _role_family_for_listing(listing: SourceListing) -> dict[str, Any]:
    if listing.job is not None:
        role = role_family_for_job(listing.job)
    else:
        role = canonical_role_family(listing.source_title)
    return {
        "id": role.id,
        "label": role.label,
        "confidence": role.confidence,
        "matched_phrase": role.matched_phrase,
    }


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


def _count_active_jobs(session: Session) -> int:
    query = select(func.count()).select_from(Job).where(Job.closed_at.is_(None))
    return int(session.scalar(query) or 0)


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
