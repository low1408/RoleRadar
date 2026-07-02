"""SQLAlchemy models for RoleRadar storage."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from roleradar.storage.database import Base


def utc_now() -> datetime:
    """Return an aware UTC timestamp for default values."""
    return datetime.now(UTC)


class IngestionRun(Base):
    """One execution of a source ingestion workflow."""

    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parameters: Mapped[dict | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)

    source_listings: Mapped[list[SourceListing]] = relationship(
        back_populates="ingestion_run"
    )


class Company(Base):
    """Canonical company record."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    jobs: Mapped[list[Job]] = relationship(back_populates="company")


class Job(Base):
    """Canonical job posting assembled from one or more source listings."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    title: Mapped[str] = mapped_column(String(500))
    normalized_title: Mapped[str] = mapped_column(String(500), index=True)
    canonical_url: Mapped[str | None] = mapped_column(Text, unique=True)
    location: Mapped[str | None] = mapped_column(String(255))
    workplace_type: Mapped[str | None] = mapped_column(String(64))
    description_text: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)

    company: Mapped[Company | None] = relationship(back_populates="jobs")
    source_listings: Mapped[list[SourceListing]] = relationship(back_populates="job")
    job_skills: Mapped[list[JobSkill]] = relationship(back_populates="job")
    duplicate_candidates: Mapped[list[DuplicateJobCandidate]] = relationship(
        foreign_keys="DuplicateJobCandidate.job_id",
        back_populates="job",
    )


class SourceListing(Base):
    """Source-specific listing record with original provenance preserved."""

    __tablename__ = "source_listings"
    __table_args__ = (
        UniqueConstraint("source", "source_job_id", name="uq_source_listing_identity"),
        Index("ix_source_listings_source_url", "source", "source_url"),
        Index("ix_source_listings_canonical_url", "canonical_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    source: Mapped[str] = mapped_column(String(64), index=True)
    source_job_id: Mapped[str] = mapped_column(String(255))
    canonical_url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    source_company_name: Mapped[str | None] = mapped_column(String(255), index=True)
    source_title: Mapped[str | None] = mapped_column(String(500), index=True)
    location: Mapped[str | None] = mapped_column(String(255))
    workplace_type: Mapped[str | None] = mapped_column(String(64))
    description_text: Mapped[str | None] = mapped_column(Text)
    salary_min: Mapped[float | None] = mapped_column(Float)
    salary_max: Mapped[float | None] = mapped_column(Float)
    salary_currency: Mapped[str | None] = mapped_column(String(3))
    salary_interval: Mapped[str | None] = mapped_column(String(32))
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    ingestion_run: Mapped[IngestionRun | None] = relationship(
        back_populates="source_listings"
    )
    job: Mapped[Job | None] = relationship(back_populates="source_listings")
    observations: Mapped[list[PostingObservation]] = relationship(
        back_populates="source_listing"
    )


class Skill(Base):
    """Canonical skill from a taxonomy or curated local seed."""

    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("normalized_name", "source_taxonomy", name="uq_skill_taxonomy"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str | None] = mapped_column(String(255))
    source_taxonomy: Mapped[str] = mapped_column(String(255), default="local")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    aliases: Mapped[list[SkillAlias]] = relationship(back_populates="skill")
    job_skills: Mapped[list[JobSkill]] = relationship(back_populates="skill")


class SkillAlias(Base):
    """A configured text alias used to match one canonical skill."""

    __tablename__ = "skill_aliases"
    __table_args__ = (
        UniqueConstraint("skill_id", "normalized_alias", name="uq_skill_alias"),
        Index("ix_skill_aliases_normalized_alias", "normalized_alias"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"))
    alias: Mapped[str] = mapped_column(String(255))
    normalized_alias: Mapped[str] = mapped_column(String(255))
    match_type: Mapped[str] = mapped_column(String(64), default="literal")
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)

    skill: Mapped[Skill] = relationship(back_populates="aliases")


class JobSkill(Base):
    """Skill extracted from a canonical job."""

    __tablename__ = "job_skills"
    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "skill_id",
            "extraction_method",
            name="uq_job_skill_method",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id"))
    extraction_method: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    matched_text: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[Job] = relationship(back_populates="job_skills")
    skill: Mapped[Skill] = relationship(back_populates="job_skills")


class PostingObservation(Base):
    """A point-in-time observation of a source listing."""

    __tablename__ = "posting_observations"
    __table_args__ = (
        Index("ix_posting_observations_listing_time", "source_listing_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_listing_id: Mapped[int] = mapped_column(ForeignKey("source_listings.id"))
    ingestion_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)

    source_listing: Mapped[SourceListing] = relationship(back_populates="observations")


class DuplicateJobCandidate(Base):
    """Reviewable candidate match between two canonical jobs."""

    __tablename__ = "duplicate_job_candidates"
    __table_args__ = (
        UniqueConstraint("job_id", "candidate_job_id", name="uq_duplicate_job_candidate"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    candidate_job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    match_type: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float, default=1.0)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    job: Mapped[Job] = relationship(
        foreign_keys=[job_id],
        back_populates="duplicate_candidates",
    )
    candidate_job: Mapped[Job] = relationship(foreign_keys=[candidate_job_id])
