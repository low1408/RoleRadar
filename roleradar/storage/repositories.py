"""Small repository helpers for storage-layer operations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from roleradar.ingestion.normalize_jobs import extract_job_description_sections
from roleradar.storage.models import (
    Company,
    DeletedListing,
    DuplicateAuditLog,
    DuplicateJobCandidate,
    IngestionRun,
    Job,
    JobSkill,
    PostingObservation,
    Skill,
    SkillAlias,
    SourceListing,
)

STRUCTURED_DUPLICATE_FIELDS = {
    "responsibilities": "responsibilities",
    "required_competencies_and_certifications": "required competencies",
    "preferred_competencies_and_qualifications": "preferred qualifications",
}
MIN_STRUCTURED_SIGNAL_LENGTH = 20


@dataclass(frozen=True)
class DuplicateCandidateMatch:
    """Evidence for one reviewable duplicate candidate."""

    candidate_job: Job
    match_type: str
    score: float
    reason: str


def normalize_text(value: str) -> str:
    """Normalize text for stable matching keys."""
    return re.sub(r"\s+", " ", value.strip().casefold())


class IngestionRunRepository:
    """Repository for ingestion run lifecycle records."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, *, source: str, parameters: dict[str, Any] | None = None
    ) -> IngestionRun:
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

    def get_or_create_company(
        self, *, name: str, industry: str | None = None
    ) -> Company:
        normalized_name = normalize_text(name)
        company = self.session.scalar(
            select(Company).where(Company.normalized_name == normalized_name)
        )
        if company is not None:
            if industry and company.industry != industry:
                company.industry = industry
            return company

        company = Company(
            name=name.strip(), normalized_name=normalized_name, industry=industry
        )
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
        role_family_id: str | None = None,
        raw_payload: dict[str, Any] | None = None,
    ) -> Job:
        if canonical_url:
            job = self.session.scalar(
                select(Job).where(Job.canonical_url == canonical_url)
            )
            if job is not None:
                job.last_seen_at = datetime.now(UTC)
                job.description_text = description_text or job.description_text
                job.content_hash = content_hash or job.content_hash
                job.role_family_id = role_family_id or job.role_family_id
                job.raw_payload = raw_payload or job.raw_payload
                return job

        job = Job(
            title=title.strip(),
            normalized_title=normalize_text(title),
            role_family_id=role_family_id,
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
        text_quality: str | None = None,
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
        if listing.job is not None and listing.job.closed_at is not None:
            listing.job.closed_at = None
        listing.canonical_url = canonical_url
        listing.source_url = source_url
        listing.source_company_name = source_company_name
        listing.source_title = source_title
        listing.location = location
        listing.workplace_type = workplace_type
        listing.description_text = description_text
        listing.text_quality = text_quality or "full_text"
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

    def find_duplicate_candidate_matches(
        self,
        job: Job,
    ) -> list[DuplicateCandidateMatch]:
        """Find conservative cross-source duplicate candidates for one job."""
        if job.id is None or job.company is None or job.closed_at is not None:
            return []

        filters = [
            Job.id != job.id,
            Job.closed_at.is_(None),
            Job.company_id == job.company_id,
            Job.normalized_title == job.normalized_title,
        ]
        if job.location:
            filters.append(Job.location == job.location)

        if job.canonical_url:
            filters.append(Job.canonical_url != job.canonical_url)

        candidates = self.session.scalars(select(Job).where(*filters)).all()
        matches: list[DuplicateCandidateMatch] = []
        for candidate in candidates:
            if not _jobs_have_distinct_sources(job, candidate):
                continue
            match = _duplicate_match_evidence(job, candidate)
            if match is None:
                continue
            matches.append(
                DuplicateCandidateMatch(
                    candidate_job=candidate,
                    match_type=match.match_type,
                    score=match.score,
                    reason=match.reason,
                )
            )
        return matches

    def find_duplicate_candidates(self, job: Job) -> list[Job]:
        """Find conservative cross-source duplicate candidate jobs."""
        return [
            match.candidate_job for match in self.find_duplicate_candidate_matches(job)
        ]

    def record_duplicate_candidate(
        self,
        *,
        job: Job,
        candidate_job: Job,
        match_type: str,
        score: float,
        reason: str,
    ) -> DuplicateJobCandidate:
        """Persist a reviewable duplicate candidate without merging source listings."""
        first_job, second_job = sorted([job, candidate_job], key=lambda item: item.id)
        existing = self.session.scalar(
            select(DuplicateJobCandidate).where(
                DuplicateJobCandidate.job_id == first_job.id,
                DuplicateJobCandidate.candidate_job_id == second_job.id,
            )
        )
        if existing is not None:
            existing.match_type = match_type
            existing.score = max(existing.score, score)
            existing.reason = reason
            return existing

        candidate = DuplicateJobCandidate(
            job=first_job,
            candidate_job=second_job,
            match_type=match_type,
            score=score,
            reason=reason,
        )
        self.session.add(candidate)
        self.session.flush()
        return candidate

    def list_duplicate_candidates(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[DuplicateJobCandidate]:
        """Return reviewable duplicate candidates for the admin API."""
        query = select(DuplicateJobCandidate).order_by(
            DuplicateJobCandidate.created_at.desc(),
            DuplicateJobCandidate.id.desc(),
        )
        if status:
            query = query.where(DuplicateJobCandidate.status == status)
        return list(self.session.scalars(query.limit(limit).offset(offset)).all())

    def get_duplicate_candidate(
        self, duplicate_candidate_id: int
    ) -> DuplicateJobCandidate | None:
        """Return one duplicate candidate by id."""
        return self.session.get(DuplicateJobCandidate, duplicate_candidate_id)

    def resolve_duplicate_candidate(
        self,
        *,
        duplicate_candidate: DuplicateJobCandidate,
        action: str,
        actor: str = "local-user",
        reason: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> DuplicateAuditLog:
        """Mark a duplicate candidate reviewed and append an audit record."""
        status_by_action = {
            "merge": "merged",
            "dismiss": "dismissed",
            "keep_separate": "kept_separate",
        }
        if action not in status_by_action:
            raise ValueError(f"unsupported duplicate resolution action: {action}")

        previous_status = duplicate_candidate.status
        merge_payload: dict[str, Any] | None = None
        if action == "merge":
            merge_payload = self._merge_duplicate_jobs(duplicate_candidate)
        duplicate_candidate.status = status_by_action[action]
        audit_payload = {**(payload or {})}
        if merge_payload is not None:
            audit_payload["merge"] = merge_payload
        audit_log = DuplicateAuditLog(
            duplicate_candidate=duplicate_candidate,
            action=action,
            actor=actor,
            reason=reason,
            previous_status=previous_status,
            new_status=duplicate_candidate.status,
            payload=audit_payload or None,
        )
        self.session.add(audit_log)
        self.session.flush()
        return audit_log

    def _merge_duplicate_jobs(
        self,
        duplicate_candidate: DuplicateJobCandidate,
    ) -> dict[str, Any]:
        keeper = duplicate_candidate.job
        redundant = duplicate_candidate.candidate_job
        moved_source_listing_ids: list[int] = []
        moved_job_skill_ids: list[int] = []
        removed_job_skill_ids: list[int] = []

        for listing in list(redundant.source_listings):
            listing.job = keeper
            if listing.id is not None:
                moved_source_listing_ids.append(listing.id)

        for job_skill in list(redundant.job_skills):
            existing = self.session.scalar(
                select(JobSkill).where(
                    JobSkill.job_id == keeper.id,
                    JobSkill.skill_id == job_skill.skill_id,
                    JobSkill.extraction_method == job_skill.extraction_method,
                )
            )
            if existing is not None:
                existing.confidence = max(existing.confidence, job_skill.confidence)
                existing.matched_text = job_skill.matched_text or existing.matched_text
                if job_skill.id is not None:
                    removed_job_skill_ids.append(job_skill.id)
                self.session.delete(job_skill)
                continue

            job_skill.job = keeper
            if job_skill.id is not None:
                moved_job_skill_ids.append(job_skill.id)

        if keeper.description_text is None and redundant.description_text:
            keeper.description_text = redundant.description_text
        if keeper.content_hash is None and redundant.content_hash:
            keeper.content_hash = redundant.content_hash
        if keeper.role_family_id is None and redundant.role_family_id:
            keeper.role_family_id = redundant.role_family_id
        if keeper.raw_payload is None and redundant.raw_payload:
            keeper.raw_payload = redundant.raw_payload
        if keeper.location is None and redundant.location:
            keeper.location = redundant.location
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

        redundant.closed_at = datetime.now(UTC)
        self.session.flush()
        return {
            "keeper_job_id": keeper.id,
            "redundant_job_id": redundant.id,
            "moved_source_listing_ids": moved_source_listing_ids,
            "moved_job_skill_ids": moved_job_skill_ids,
            "removed_job_skill_ids": removed_job_skill_ids,
        }

    def delete_source_listing(self, listing: SourceListing) -> None:
        """Move a source listing and its relations to the recycle bin, then delete them."""
        job = listing.job
        job_deleted = False
        duplicates = []
        if job is not None:
            remaining = self.session.scalars(
                select(SourceListing).where(
                    SourceListing.job_id == job.id,
                    SourceListing.id != listing.id
                )
            ).all()
            if not remaining:
                job_deleted = True
                duplicates = self.session.scalars(
                    select(DuplicateJobCandidate).where(
                        (DuplicateJobCandidate.job_id == job.id) |
                        (DuplicateJobCandidate.candidate_job_id == job.id)
                    )
                ).all()

        payload = {
            "source_listing": {
                "id": listing.id,
                "ingestion_run_id": listing.ingestion_run_id,
                "job_id": listing.job_id,
                "source": listing.source,
                "source_job_id": listing.source_job_id,
                "canonical_url": listing.canonical_url,
                "source_url": listing.source_url,
                "source_company_name": listing.source_company_name,
                "source_title": listing.source_title,
                "location": listing.location,
                "workplace_type": listing.workplace_type,
                "description_text": listing.description_text,
                "text_quality": listing.text_quality,
                "salary_min": listing.salary_min,
                "salary_max": listing.salary_max,
                "salary_currency": listing.salary_currency,
                "salary_interval": listing.salary_interval,
                "content_hash": listing.content_hash,
                "raw_payload": listing.raw_payload,
                "first_seen_at": listing.first_seen_at.isoformat() if listing.first_seen_at else None,
                "last_seen_at": listing.last_seen_at.isoformat() if listing.last_seen_at else None,
                "source_updated_at": listing.source_updated_at.isoformat() if listing.source_updated_at else None,
            },
            "observations": [
                {
                    "id": obs.id,
                    "ingestion_run_id": obs.ingestion_run_id,
                    "observed_at": obs.observed_at.isoformat() if obs.observed_at else None,
                    "is_active": obs.is_active,
                    "content_hash": obs.content_hash,
                    "raw_payload": obs.raw_payload,
                    "source_updated_at": obs.source_updated_at.isoformat() if obs.source_updated_at else None,
                }
                for obs in listing.observations
            ],
            "job_deleted": job_deleted,
        }

        if job_deleted:
            payload["job"] = {
                "id": job.id,
                "company_id": job.company_id,
                "title": job.title,
                "normalized_title": job.normalized_title,
                "role_family_id": job.role_family_id,
                "canonical_url": job.canonical_url,
                "location": job.location,
                "workplace_type": job.workplace_type,
                "description_text": job.description_text,
                "content_hash": job.content_hash,
                "first_seen_at": job.first_seen_at.isoformat() if job.first_seen_at else None,
                "last_seen_at": job.last_seen_at.isoformat() if job.last_seen_at else None,
                "closed_at": job.closed_at.isoformat() if job.closed_at else None,
                "raw_payload": job.raw_payload,
            }
            payload["job_skills"] = [
                {
                    "id": js.id,
                    "job_id": js.job_id,
                    "skill_id": js.skill_id,
                    "extraction_method": js.extraction_method,
                    "confidence": js.confidence,
                    "matched_text": js.matched_text,
                    "created_at": js.created_at.isoformat() if js.created_at else None,
                }
                for js in job.job_skills
            ]
            payload["duplicate_candidates"] = [
                {
                    "id": dc.id,
                    "job_id": dc.job_id,
                    "candidate_job_id": dc.candidate_job_id,
                    "match_type": dc.match_type,
                    "score": dc.score,
                    "reason": dc.reason,
                    "status": dc.status,
                    "created_at": dc.created_at.isoformat() if dc.created_at else None,
                    "audit_logs": [
                        {
                            "id": al.id,
                            "duplicate_candidate_id": al.duplicate_candidate_id,
                            "action": al.action,
                            "actor": al.actor,
                            "reason": al.reason,
                            "previous_status": al.previous_status,
                            "new_status": al.new_status,
                            "payload": al.payload,
                            "created_at": al.created_at.isoformat() if al.created_at else None,
                        }
                        for al in dc.audit_logs
                    ]
                }
                for dc in duplicates
            ]

        deleted_listing = DeletedListing(
            source_listing_id=listing.id,
            payload=payload
        )
        self.session.add(deleted_listing)
        self.session.flush()

        for observation in list(listing.observations):
            self.session.delete(observation)

        self.session.delete(listing)
        self.session.flush()

        if job_deleted:
            for job_skill in list(job.job_skills):
                self.session.delete(job_skill)
            for duplicate in duplicates:
                for audit_log in list(duplicate.audit_logs):
                    self.session.delete(audit_log)
                self.session.delete(duplicate)
            self.session.delete(job)

        self.session.flush()

    def restore_source_listing(self, source_listing_id: int) -> SourceListing:
        """Restore a source listing and its relations from the recycle bin."""
        deleted_record = self.session.scalar(
            select(DeletedListing).where(DeletedListing.source_listing_id == source_listing_id)
        )
        if deleted_record is None:
            raise ValueError("Listing not found in recycle bin")

        payload = deleted_record.payload

        if payload.get("job_deleted"):
            job_data = payload["job"]
            job = Job(
                id=job_data["id"],
                company_id=job_data["company_id"],
                title=job_data["title"],
                normalized_title=job_data["normalized_title"],
                role_family_id=job_data["role_family_id"],
                canonical_url=job_data["canonical_url"],
                location=job_data["location"],
                workplace_type=job_data["workplace_type"],
                description_text=job_data["description_text"],
                content_hash=job_data["content_hash"],
                first_seen_at=datetime.fromisoformat(job_data["first_seen_at"]) if job_data["first_seen_at"] else None,
                last_seen_at=datetime.fromisoformat(job_data["last_seen_at"]) if job_data["last_seen_at"] else None,
                closed_at=datetime.fromisoformat(job_data["closed_at"]) if job_data["closed_at"] else None,
                raw_payload=job_data["raw_payload"],
            )
            self.session.add(job)
            self.session.flush()

            for js_data in payload.get("job_skills", []):
                js = JobSkill(
                    id=js_data["id"],
                    job_id=js_data["job_id"],
                    skill_id=js_data["skill_id"],
                    extraction_method=js_data["extraction_method"],
                    confidence=js_data["confidence"],
                    matched_text=js_data["matched_text"],
                    created_at=datetime.fromisoformat(js_data["created_at"]) if js_data["created_at"] else None,
                )
                self.session.add(js)

            for dc_data in payload.get("duplicate_candidates", []):
                dc = DuplicateJobCandidate(
                    id=dc_data["id"],
                    job_id=dc_data["job_id"],
                    candidate_job_id=dc_data["candidate_job_id"],
                    match_type=dc_data["match_type"],
                    score=dc_data["score"],
                    reason=dc_data["reason"],
                    status=dc_data["status"],
                    created_at=datetime.fromisoformat(dc_data["created_at"]) if dc_data["created_at"] else None,
                )
                self.session.add(dc)
                self.session.flush()

                for al_data in dc_data.get("audit_logs", []):
                    al = DuplicateAuditLog(
                        id=al_data["id"],
                        duplicate_candidate_id=al_data["duplicate_candidate_id"],
                        action=al_data["action"],
                        actor=al_data["actor"],
                        reason=al_data["reason"],
                        previous_status=al_data["previous_status"],
                        new_status=al_data["new_status"],
                        payload=al_data["payload"],
                        created_at=datetime.fromisoformat(al_data["created_at"]) if al_data["created_at"] else None,
                    )
                    self.session.add(al)

        sl_data = payload["source_listing"]
        listing = SourceListing(
            id=sl_data["id"],
            ingestion_run_id=sl_data["ingestion_run_id"],
            job_id=sl_data["job_id"],
            source=sl_data["source"],
            source_job_id=sl_data["source_job_id"],
            canonical_url=sl_data["canonical_url"],
            source_url=sl_data["source_url"],
            source_company_name=sl_data["source_company_name"],
            source_title=sl_data["source_title"],
            location=sl_data["location"],
            workplace_type=sl_data["workplace_type"],
            description_text=sl_data["description_text"],
            text_quality=sl_data["text_quality"],
            salary_min=sl_data["salary_min"],
            salary_max=sl_data["salary_max"],
            salary_currency=sl_data["salary_currency"],
            salary_interval=sl_data["salary_interval"],
            content_hash=sl_data["content_hash"],
            raw_payload=sl_data["raw_payload"],
            first_seen_at=datetime.fromisoformat(sl_data["first_seen_at"]) if sl_data["first_seen_at"] else None,
            last_seen_at=datetime.fromisoformat(sl_data["last_seen_at"]) if sl_data["last_seen_at"] else None,
            source_updated_at=datetime.fromisoformat(sl_data["source_updated_at"]) if sl_data["source_updated_at"] else None,
        )
        self.session.add(listing)
        self.session.flush()

        for obs_data in payload.get("observations", []):
            obs = PostingObservation(
                id=obs_data["id"],
                source_listing_id=listing.id,
                ingestion_run_id=obs_data["ingestion_run_id"],
                observed_at=datetime.fromisoformat(obs_data["observed_at"]) if obs_data["observed_at"] else None,
                is_active=obs_data["is_active"],
                content_hash=obs_data["content_hash"],
                raw_payload=obs_data["raw_payload"],
                source_updated_at=datetime.fromisoformat(obs_data["source_updated_at"]) if obs_data["source_updated_at"] else None,
            )
            self.session.add(obs)

        self.session.delete(deleted_record)
        self.session.flush()

        return listing


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


def _jobs_have_distinct_sources(first: Job, second: Job) -> bool:
    first_sources = {listing.source for listing in first.source_listings}
    second_sources = {listing.source for listing in second.source_listings}
    return bool(first_sources and second_sources and first_sources != second_sources)


def _duplicate_match_evidence(
    first: Job,
    second: Job,
) -> DuplicateCandidateMatch | None:
    if first.canonical_url and first.canonical_url == second.canonical_url:
        return DuplicateCandidateMatch(
            candidate_job=second,
            match_type="canonical_url",
            score=1.0,
            reason="same canonical job URL across distinct sources",
        )
    if first.content_hash and first.content_hash == second.content_hash:
        return DuplicateCandidateMatch(
            candidate_job=second,
            match_type="content_hash",
            score=0.95,
            reason="same normalized company, title, location, and content hash",
        )

    listing_matches = [
        listing_match
        for first_listing in first.source_listings
        for second_listing in second.source_listings
        if first_listing.source != second_listing.source
        for listing_match in [
            _source_listing_match_evidence(first_listing, second_listing)
        ]
        if listing_match is not None
    ]
    if not listing_matches:
        return None
    return max(listing_matches, key=lambda match: match.score)


def _source_listing_match_evidence(
    first: SourceListing,
    second: SourceListing,
) -> DuplicateCandidateMatch | None:
    if second.job is None:
        return None

    signals: list[str] = []
    structured_matches = _matching_structured_fields(first, second)
    salary_matches = _salary_matches(first, second)
    workplace_matches = _non_empty_text_matches(
        first.workplace_type,
        second.workplace_type,
    )
    description_matches = _non_empty_text_matches(
        first.description_text,
        second.description_text,
    )

    for field_name in structured_matches:
        signals.append(f"matching {STRUCTURED_DUPLICATE_FIELDS[field_name]}")
    if salary_matches:
        signals.append("matching salary range")
    if workplace_matches:
        signals.append("matching workplace type")
    if description_matches:
        signals.append("matching normalized description")

    if len(structured_matches) >= 3:
        return DuplicateCandidateMatch(
            candidate_job=second.job,
            match_type="structured_fields",
            score=0.95,
            reason=_duplicate_reason(signals),
        )
    if len(structured_matches) >= 2:
        return DuplicateCandidateMatch(
            candidate_job=second.job,
            match_type="structured_fields",
            score=0.9 if salary_matches else 0.88,
            reason=_duplicate_reason(signals),
        )
    if len(structured_matches) == 1 and salary_matches:
        return DuplicateCandidateMatch(
            candidate_job=second.job,
            match_type="structured_fields_salary",
            score=0.86,
            reason=_duplicate_reason(signals),
        )
    if description_matches and salary_matches:
        return DuplicateCandidateMatch(
            candidate_job=second.job,
            match_type="description_salary",
            score=0.86,
            reason=_duplicate_reason(signals),
        )
    if description_matches and workplace_matches:
        return DuplicateCandidateMatch(
            candidate_job=second.job,
            match_type="description_workplace",
            score=0.84,
            reason=_duplicate_reason(signals),
        )
    return None


def _duplicate_reason(signals: list[str]) -> str:
    return (
        "same normalized company, title, location, and "
        f"{'; '.join(signals)} across distinct sources"
    )


def _matching_structured_fields(
    first: SourceListing,
    second: SourceListing,
) -> list[str]:
    first_sections = _structured_sections_for_listing(first)
    second_sections = _structured_sections_for_listing(second)
    matches: list[str] = []
    for field_name in STRUCTURED_DUPLICATE_FIELDS:
        first_value = _substantive_normalized_text(first_sections.get(field_name))
        second_value = _substantive_normalized_text(second_sections.get(field_name))
        if first_value and first_value == second_value:
            matches.append(field_name)
    return matches


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


def _salary_matches(first: SourceListing, second: SourceListing) -> bool:
    if first.salary_min is None and first.salary_max is None:
        return False
    if second.salary_min is None and second.salary_max is None:
        return False
    if not _nullable_float_matches(first.salary_min, second.salary_min):
        return False
    if not _nullable_float_matches(first.salary_max, second.salary_max):
        return False
    if first.salary_currency and second.salary_currency:
        if normalize_text(first.salary_currency) != normalize_text(
            second.salary_currency
        ):
            return False
    if first.salary_interval and second.salary_interval:
        if normalize_text(first.salary_interval) != normalize_text(
            second.salary_interval
        ):
            return False
    return True


def _nullable_float_matches(first: float | None, second: float | None) -> bool:
    if first is None or second is None:
        return first is second
    return round(float(first), 2) == round(float(second), 2)


def _non_empty_text_matches(first: str | None, second: str | None) -> bool:
    first_value = _substantive_normalized_text(first)
    second_value = _substantive_normalized_text(second)
    return bool(first_value and first_value == second_value)


def _substantive_normalized_text(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_text(value)
    if len(normalized) < MIN_STRUCTURED_SIGNAL_LENGTH:
        return None
    return normalized
