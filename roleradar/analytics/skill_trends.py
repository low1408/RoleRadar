"""Current-snapshot skill reporting queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from roleradar.storage.models import Job, PostingObservation, SourceListing

DEFAULT_ROLE_KEYWORDS = ("data", "engineer", "analyst", "software", "product")


@dataclass(frozen=True)
class SkillCount:
    """Count active jobs requiring one skill."""

    skill_name: str
    job_count: int


@dataclass(frozen=True)
class SkillSourceCount:
    """Count active source listings requiring one skill."""

    source: str
    skill_name: str
    posting_count: int


@dataclass(frozen=True)
class SkillCompanyCount:
    """Count active jobs at one company requiring one skill."""

    company_name: str
    skill_name: str
    job_count: int


@dataclass(frozen=True)
class SkillRoleKeywordCount:
    """Count active jobs matching a role keyword requiring one skill."""

    role_keyword: str
    skill_name: str
    job_count: int


@dataclass(frozen=True)
class SkillExtractionCoverage:
    """Text availability and extraction coverage for skill reports."""

    source: str
    total_posting_count: int
    full_text_posting_count: int
    snippet_posting_count: int
    extracted_posting_count: int

    @property
    def full_text_rate(self) -> float:
        """Return share of active postings with full descriptions."""
        if not self.total_posting_count:
            return 0.0
        return self.full_text_posting_count / self.total_posting_count


def top_skills(
    session: Session,
    *,
    days: int | None = None,
    limit: int = 10,
) -> list[SkillCount]:
    """Return top skills by active canonical job count."""
    grouped: dict[str, set[int]] = {}
    for job in _active_jobs(session, days=days):
        if job.id is None:
            continue
        for job_skill in job.job_skills:
            if job_skill.skill is None:
                continue
            grouped.setdefault(job_skill.skill.name, set()).add(job.id)

    rows = [
        SkillCount(skill_name=skill_name, job_count=len(job_ids))
        for skill_name, job_ids in grouped.items()
    ]
    return sorted(rows, key=lambda row: (-row.job_count, row.skill_name))[:limit]


def skills_by_source(
    session: Session,
    *,
    days: int | None = None,
    limit: int = 10,
) -> list[SkillSourceCount]:
    """Return skills grouped by source listing provenance."""
    grouped: dict[tuple[str, str], int] = {}
    for listing in _active_source_listings(session, days=days):
        if listing.job is None:
            continue
        seen_skill_names = {
            job_skill.skill.name
            for job_skill in listing.job.job_skills
            if job_skill.skill is not None
        }
        for skill_name in seen_skill_names:
            key = (listing.source, skill_name)
            grouped[key] = grouped.get(key, 0) + 1

    rows = [
        SkillSourceCount(
            source=source,
            skill_name=skill_name,
            posting_count=posting_count,
        )
        for (source, skill_name), posting_count in grouped.items()
    ]
    return sorted(
        rows,
        key=lambda row: (row.source, -row.posting_count, row.skill_name),
    )[:limit]


def skills_by_company(
    session: Session,
    *,
    days: int | None = None,
    limit: int = 10,
) -> list[SkillCompanyCount]:
    """Return skills grouped by canonical company."""
    grouped: dict[tuple[str, str], set[int]] = {}
    for job in _active_jobs(session, days=days):
        if job.id is None:
            continue
        company_name = job.company.name if job.company is not None else "UNKNOWN"
        for job_skill in job.job_skills:
            if job_skill.skill is None:
                continue
            key = (company_name, job_skill.skill.name)
            grouped.setdefault(key, set()).add(job.id)

    rows = [
        SkillCompanyCount(
            company_name=company_name,
            skill_name=skill_name,
            job_count=len(job_ids),
        )
        for (company_name, skill_name), job_ids in grouped.items()
    ]
    return sorted(
        rows,
        key=lambda row: (row.company_name, -row.job_count, row.skill_name),
    )[:limit]


def skills_by_role_keyword(
    session: Session,
    *,
    days: int | None = None,
    role_keywords: tuple[str, ...] = DEFAULT_ROLE_KEYWORDS,
    limit_per_keyword: int = 5,
) -> list[SkillRoleKeywordCount]:
    """Return skills grouped by configured role/title keywords."""
    results: list[SkillRoleKeywordCount] = []
    for keyword in role_keywords:
        normalized_keyword = _normalize_keyword(keyword)
        grouped: dict[str, set[int]] = {}
        for job in _active_jobs(session, days=days):
            if (
                job.id is None
                or not normalized_keyword
                or normalized_keyword not in job.normalized_title
            ):
                continue
            for job_skill in job.job_skills:
                if job_skill.skill is None:
                    continue
                grouped.setdefault(job_skill.skill.name, set()).add(job.id)

        rows = [
            SkillRoleKeywordCount(
                role_keyword=keyword,
                skill_name=skill_name,
                job_count=len(job_ids),
            )
            for skill_name, job_ids in grouped.items()
        ]
        results.extend(
            sorted(rows, key=lambda row: (-row.job_count, row.skill_name))[
                :limit_per_keyword
            ]
        )
    return results


def skill_extraction_coverage_by_source(
    session: Session,
    *,
    days: int | None = None,
) -> list[SkillExtractionCoverage]:
    """Return text-quality coverage by source for skill analytics."""
    grouped: dict[str, list[SourceListing]] = {}
    for listing in _active_source_listings(session, days=days):
        grouped.setdefault(listing.source, []).append(listing)

    rows: list[SkillExtractionCoverage] = []
    for source, listings in sorted(grouped.items()):
        full_text_count = sum(
            1 for listing in listings if listing.text_quality == "full_text"
        )
        snippet_count = sum(
            1 for listing in listings if listing.text_quality == "snippet"
        )
        extracted_count = sum(
            1
            for listing in listings
            if listing.job is not None and bool(listing.job.job_skills)
        )
        rows.append(
            SkillExtractionCoverage(
                source=source,
                total_posting_count=len(listings),
                full_text_posting_count=full_text_count,
                snippet_posting_count=snippet_count,
                extracted_posting_count=extracted_count,
            )
        )
    return rows


def _active_jobs(session: Session, *, days: int | None) -> list[Job]:
    query = select(Job).where(Job.closed_at.is_(None))
    if days is not None:
        query = query.where(Job.last_seen_at >= _cutoff(days))
    return list(session.scalars(query).unique().all())


def _active_source_listings(
    session: Session,
    *,
    days: int | None = None,
) -> list[SourceListing]:
    latest_observation = (
        select(
            PostingObservation.source_listing_id.label("source_listing_id"),
            func.max(PostingObservation.observed_at).label("observed_at"),
        )
        .group_by(PostingObservation.source_listing_id)
        .subquery()
    )
    query = (
        select(SourceListing)
        .join(Job, Job.id == SourceListing.job_id)
        .outerjoin(
            latest_observation,
            latest_observation.c.source_listing_id == SourceListing.id,
        )
        .outerjoin(
            PostingObservation,
            and_(
                PostingObservation.source_listing_id == SourceListing.id,
                PostingObservation.observed_at == latest_observation.c.observed_at,
            ),
        )
        .where(
            Job.closed_at.is_(None),
            or_(
                PostingObservation.id.is_(None),
                PostingObservation.is_active.is_(True),
            ),
        )
    )
    if days is not None:
        query = query.where(SourceListing.last_seen_at >= _cutoff(days))
    return list(session.scalars(query).unique().all())


def _cutoff(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _normalize_keyword(keyword: str) -> str:
    return " ".join(keyword.strip().casefold().split())
