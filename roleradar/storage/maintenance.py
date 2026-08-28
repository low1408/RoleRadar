"""Database retention and maintenance operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from roleradar.storage.models import (
    DuplicateAuditLog,
    DuplicateJobCandidate,
    Job,
    JobSkill,
    PostingObservation,
    SourceListing,
)


@dataclass(frozen=True)
class PruneRolesResult:
    """Counts of records selected or removed by role retention."""

    jobs: int = 0
    source_listings: int = 0
    observations: int = 0
    job_skills: int = 0
    duplicate_candidates: int = 0
    duplicate_audit_logs: int = 0


def prune_closed_roles(
    session: Session,
    *,
    closed_before: datetime,
    dry_run: bool = False,
) -> PruneRolesResult:
    """Delete jobs closed before a cutoff and all dependent records."""
    job_ids = list(
        session.scalars(
            select(Job.id).where(
                Job.closed_at.is_not(None),
                Job.closed_at < closed_before,
            )
        )
    )
    if not job_ids:
        return PruneRolesResult()

    source_listing_ids = list(
        session.scalars(
            select(SourceListing.id).where(SourceListing.job_id.in_(job_ids))
        )
    )
    duplicate_candidate_ids = list(
        session.scalars(
            select(DuplicateJobCandidate.id).where(
                or_(
                    DuplicateJobCandidate.job_id.in_(job_ids),
                    DuplicateJobCandidate.candidate_job_id.in_(job_ids),
                )
            )
        )
    )

    result = PruneRolesResult(
        jobs=len(job_ids),
        source_listings=len(source_listing_ids),
        observations=_count_matching(
            session,
            PostingObservation,
            PostingObservation.source_listing_id.in_(source_listing_ids),
        ),
        job_skills=_count_matching(
            session,
            JobSkill,
            JobSkill.job_id.in_(job_ids),
        ),
        duplicate_candidates=len(duplicate_candidate_ids),
        duplicate_audit_logs=_count_matching(
            session,
            DuplicateAuditLog,
            DuplicateAuditLog.duplicate_candidate_id.in_(duplicate_candidate_ids),
        ),
    )
    if dry_run:
        return result

    _delete_matching(
        session,
        DuplicateAuditLog,
        DuplicateAuditLog.duplicate_candidate_id.in_(duplicate_candidate_ids),
    )
    _delete_matching(
        session,
        DuplicateJobCandidate,
        DuplicateJobCandidate.id.in_(duplicate_candidate_ids),
    )
    _delete_matching(
        session,
        PostingObservation,
        PostingObservation.source_listing_id.in_(source_listing_ids),
    )
    _delete_matching(session, SourceListing, SourceListing.id.in_(source_listing_ids))
    _delete_matching(session, JobSkill, JobSkill.job_id.in_(job_ids))
    _delete_matching(session, Job, Job.id.in_(job_ids))
    session.flush()
    return result


def _count_matching(session: Session, model, condition) -> int:
    return int(
        session.scalar(select(func.count()).select_from(model).where(condition)) or 0
    )


def _delete_matching(session: Session, model, condition) -> None:
    session.execute(
        delete(model).where(condition).execution_options(synchronize_session=False)
    )
