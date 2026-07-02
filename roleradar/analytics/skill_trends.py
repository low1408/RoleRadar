"""Current-snapshot skill reporting queries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from roleradar.storage.models import Company, Job, JobSkill, Skill, SourceListing


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


def top_skills(
    session: Session,
    *,
    days: int | None = None,
    limit: int = 10,
) -> list[SkillCount]:
    """Return top skills by active canonical job count."""
    query = (
        select(
            Skill.name,
            func.count(func.distinct(JobSkill.job_id)).label("job_count"),
        )
        .join(JobSkill, JobSkill.skill_id == Skill.id)
        .join(Job, Job.id == JobSkill.job_id)
        .where(*_active_recent_job_filters(days))
        .group_by(Skill.id)
        .order_by(desc("job_count"), Skill.name)
        .limit(limit)
    )
    rows = session.execute(query).all()

    return [SkillCount(skill_name=row[0], job_count=row[1]) for row in rows]


def skills_by_source(
    session: Session,
    *,
    days: int | None = None,
    limit: int = 10,
) -> list[SkillSourceCount]:
    """Return top skills grouped by original source."""
    query = (
        select(
            SourceListing.source,
            Skill.name,
            func.count(func.distinct(SourceListing.id)).label("posting_count"),
        )
        .join(Job, Job.id == SourceListing.job_id)
        .join(JobSkill, JobSkill.job_id == Job.id)
        .join(Skill, Skill.id == JobSkill.skill_id)
        .where(*_active_recent_listing_filters(days))
        .group_by(SourceListing.source, Skill.id)
        .order_by(SourceListing.source, desc("posting_count"), Skill.name)
        .limit(limit)
    )
    rows = session.execute(query).all()

    return [
        SkillSourceCount(source=row[0], skill_name=row[1], posting_count=row[2])
        for row in rows
    ]


def skills_by_company(
    session: Session,
    *,
    days: int | None = None,
    limit: int = 10,
) -> list[SkillCompanyCount]:
    """Return top skills grouped by canonical company."""
    query = (
        select(
            Company.name,
            Skill.name,
            func.count(func.distinct(Job.id)).label("job_count"),
        )
        .join(Job, Job.company_id == Company.id)
        .join(JobSkill, JobSkill.job_id == Job.id)
        .join(Skill, Skill.id == JobSkill.skill_id)
        .where(*_active_recent_job_filters(days))
        .group_by(Company.id, Skill.id)
        .order_by(Company.name, desc("job_count"), Skill.name)
        .limit(limit)
    )
    rows = session.execute(query).all()

    return [
        SkillCompanyCount(company_name=row[0], skill_name=row[1], job_count=row[2])
        for row in rows
    ]


def skills_by_role_keyword(
    session: Session,
    *,
    days: int | None = None,
    role_keywords: tuple[str, ...] = DEFAULT_ROLE_KEYWORDS,
    limit_per_keyword: int = 5,
) -> list[SkillRoleKeywordCount]:
    """Return top skills for configured role/title keywords."""
    results: list[SkillRoleKeywordCount] = []

    for keyword in role_keywords:
        pattern = f"%{_normalize_keyword(keyword)}%"
        query = (
            select(
                Skill.name,
                func.count(func.distinct(Job.id)).label("job_count"),
            )
            .join(JobSkill, JobSkill.skill_id == Skill.id)
            .join(Job, Job.id == JobSkill.job_id)
            .where(
                *_active_recent_job_filters(days),
                Job.normalized_title.like(pattern),
            )
            .group_by(Skill.id)
            .order_by(desc("job_count"), Skill.name)
            .limit(limit_per_keyword)
        )
        rows = session.execute(query).all()
        results.extend(
            SkillRoleKeywordCount(
                role_keyword=keyword,
                skill_name=row[0],
                job_count=row[1],
            )
            for row in rows
        )

    return results


def _active_recent_job_filters(days: int | None) -> tuple[object, ...]:
    filters: list[object] = [Job.closed_at.is_(None)]
    if days is not None:
        filters.append(Job.last_seen_at >= _cutoff(days))
    return tuple(filters)


def _active_recent_listing_filters(days: int | None) -> tuple[object, ...]:
    filters: list[object] = [Job.closed_at.is_(None)]
    if days is not None:
        filters.append(SourceListing.last_seen_at >= _cutoff(days))
    return tuple(filters)


def _cutoff(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _normalize_keyword(keyword: str) -> str:
    return re.sub(r"\s+", " ", keyword.strip().casefold())
