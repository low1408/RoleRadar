"""Small repository helpers for storage-layer operations."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from roleradar.storage.models import (
    Company,
    IngestionRun,
    Job,
    JobSkill,
    PostingObservation,
    Skill,
    SkillAlias,
    SourceListing,
)


def normalize_text(value: str) -> str:
    """Normalize text for stable matching keys."""
    return re.sub(r"\s+", " ", value.strip().casefold())


class IngestionRunRepository:
    """Repository for ingestion run lifecycle records."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, source: str, parameters: dict[str, Any] | None = None) -> IngestionRun:
        run = IngestionRun(source=source, parameters=parameters, status="running")
        self.session.add(run)
        self.session.flush()
        return run

    def complete(self, run: IngestionRun, *, status: str = "completed") -> IngestionRun:
        run.status = status
        run.completed_at = datetime.now(UTC)
        self.session.flush()
        return run


class JobRepository:
    """Repository for canonical companies, jobs, source listings, and observations."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_company(self, *, name: str, industry: str | None = None) -> Company:
        normalized_name = normalize_text(name)
        company = self.session.scalar(
            select(Company).where(Company.normalized_name == normalized_name)
        )
        if company is not None:
            if industry and company.industry != industry:
                company.industry = industry
            return company

        company = Company(name=name.strip(), normalized_name=normalized_name, industry=industry)
        self.session.add(company)
        self.session.flush()
        return company

    def get_or_create_job(
        self,
        *,
        title: str,
        company: Company | None = None,
        canonical_url: str | None = None,
        location: str | None = None,
        description_text: str | None = None,
        content_hash: str | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> Job:
        if canonical_url:
            job = self.session.scalar(select(Job).where(Job.canonical_url == canonical_url))
            if job is not None:
                job.last_seen_at = datetime.now(UTC)
                job.description_text = description_text or job.description_text
                job.content_hash = content_hash or job.content_hash
                job.raw_payload = raw_payload or job.raw_payload
                return job

        job = Job(
            title=title.strip(),
            normalized_title=normalize_text(title),
            company=company,
            canonical_url=canonical_url,
            location=location,
            description_text=description_text,
            content_hash=content_hash,
            raw_payload=raw_payload,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def upsert_source_listing(
        self,
        *,
        source: str,
        source_job_id: str,
        ingestion_run: IngestionRun | None = None,
        job: Job | None = None,
        canonical_url: str | None = None,
        source_url: str | None = None,
        source_company_name: str | None = None,
        source_title: str | None = None,
        location: str | None = None,
        workplace_type: str | None = None,
        description_text: str | None = None,
        salary_min: float | None = None,
        salary_max: float | None = None,
        salary_currency: str | None = None,
        salary_interval: str | None = None,
        content_hash: str | None = None,
        raw_payload: dict[str, Any] | None = None,
        source_updated_at: datetime | None = None,
    ) -> SourceListing:
        listing = self.session.scalar(
            select(SourceListing).where(
                SourceListing.source == source,
                SourceListing.source_job_id == source_job_id,
            )
        )
        now = datetime.now(UTC)

        if listing is None:
            listing = SourceListing(
                source=source,
                source_job_id=source_job_id,
                first_seen_at=now,
            )
            self.session.add(listing)

        listing.ingestion_run = ingestion_run
        listing.job = job or listing.job
        listing.canonical_url = canonical_url
        listing.source_url = source_url
        listing.source_company_name = source_company_name
        listing.source_title = source_title
        listing.location = location
        listing.workplace_type = workplace_type
        listing.description_text = description_text
        listing.salary_min = salary_min
        listing.salary_max = salary_max
        listing.salary_currency = salary_currency
        listing.salary_interval = salary_interval
        listing.content_hash = content_hash
        listing.raw_payload = raw_payload
        listing.source_updated_at = source_updated_at
        listing.last_seen_at = now
        self.session.flush()
        return listing

    def record_observation(
        self,
        *,
        source_listing: SourceListing,
        ingestion_run: IngestionRun | None = None,
        is_active: bool = True,
        content_hash: str | None = None,
        raw_payload: dict[str, Any] | None = None,
        source_updated_at: datetime | None = None,
    ) -> PostingObservation:
        observation = PostingObservation(
            source_listing=source_listing,
            ingestion_run_id=ingestion_run.id if ingestion_run else None,
            is_active=is_active,
            content_hash=content_hash,
            raw_payload=raw_payload,
            source_updated_at=source_updated_at,
        )
        self.session.add(observation)
        self.session.flush()
        return observation


class SkillRepository:
    """Repository for taxonomy skills, aliases, and extracted job skills."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_skill(
        self,
        *,
        name: str,
        category: str | None = None,
        source_taxonomy: str = "local",
    ) -> Skill:
        normalized_name = normalize_text(name)
        skill = self.session.scalar(
            select(Skill).where(
                Skill.normalized_name == normalized_name,
                Skill.source_taxonomy == source_taxonomy,
            )
        )
        if skill is not None:
            skill.name = name.strip()
            skill.category = category or skill.category
            return skill

        skill = Skill(
            name=name.strip(),
            normalized_name=normalized_name,
            category=category,
            source_taxonomy=source_taxonomy,
        )
        self.session.add(skill)
        self.session.flush()
        return skill

    def get_or_create_alias(
        self,
        *,
        skill: Skill,
        alias: str,
        match_type: str = "literal",
        case_sensitive: bool = False,
    ) -> SkillAlias:
        normalized_alias = normalize_text(alias)
        skill_alias = self.session.scalar(
            select(SkillAlias).where(
                SkillAlias.skill_id == skill.id,
                SkillAlias.normalized_alias == normalized_alias,
            )
        )
        if skill_alias is not None:
            skill_alias.alias = alias.strip()
            skill_alias.match_type = match_type
            skill_alias.case_sensitive = case_sensitive
            return skill_alias

        skill_alias = SkillAlias(
            skill=skill,
            alias=alias.strip(),
            normalized_alias=normalized_alias,
            match_type=match_type,
            case_sensitive=case_sensitive,
        )
        self.session.add(skill_alias)
        self.session.flush()
        return skill_alias

    def add_job_skill(
        self,
        *,
        job: Job,
        skill: Skill,
        extraction_method: str,
        confidence: float,
        matched_text: str | None,
    ) -> JobSkill:
        job_skill = self.session.scalar(
            select(JobSkill).where(
                JobSkill.job_id == job.id,
                JobSkill.skill_id == skill.id,
                JobSkill.extraction_method == extraction_method,
            )
        )
        if job_skill is not None:
            job_skill.confidence = max(job_skill.confidence, confidence)
            job_skill.matched_text = matched_text or job_skill.matched_text
            return job_skill

        job_skill = JobSkill(
            job=job,
            skill=skill,
            extraction_method=extraction_method,
            confidence=confidence,
            matched_text=matched_text,
        )
        self.session.add(job_skill)
        self.session.flush()
        return job_skill
