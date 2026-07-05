"""Shared analytics query helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from roleradar.storage.models import Job, PostingObservation, SourceListing


def active_jobs(session: Session, *, days: int | None = None) -> list[Job]:
    """Return active canonical jobs, optionally scoped by recent observation age."""
    query = select(Job).where(Job.closed_at.is_(None))
    if days is not None:
        query = query.where(Job.last_seen_at >= cutoff(days))
    return list(session.scalars(query).unique().all())


def active_source_listings(
    session: Session,
    *,
    days: int | None = None,
) -> list[SourceListing]:
    """Return source listings whose latest observation is active."""
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
        query = query.where(SourceListing.last_seen_at >= cutoff(days))
    return list(session.scalars(query).unique().all())


def cutoff(days: int) -> datetime:
    """Return a UTC cutoff timestamp for a rolling day window."""
    return datetime.now(UTC) - timedelta(days=days)
