"""Canonical role-family classification and reporting."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from roleradar.analytics.salary_trends import annualized_salary_midpoint
from roleradar.storage.models import Job, PostingObservation, SourceListing


@dataclass(frozen=True)
class RoleFamilyDefinition:
    """One canonical role family and the title phrases that identify it."""

    id: str
    label: str
    title_phrases: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalRole:
    """Canonical role-family match for one raw title."""

    id: str
    label: str
    confidence: float
    matched_phrase: str | None


@dataclass(frozen=True)
class RoleFamilySummary:
    """Market summary for a canonical role family."""

    id: str
    label: str
    job_count: int
    source_listing_count: int
    company_count: int
    salary_listing_count: int
    average_annualized_salary: float | None
    top_sources: tuple[tuple[str, int], ...]
    top_skills: tuple[tuple[str, int], ...]
    example_titles: tuple[str, ...]


@dataclass(frozen=True)
class HiringCompanySummary:
    """Hiring activity summary for one company."""

    company_name: str
    job_count: int
    source_listing_count: int
    latest_seen_at: datetime | None
    top_role_families: tuple[tuple[str, int], ...]
    top_sources: tuple[tuple[str, int], ...]


ROLE_FAMILY_DEFINITIONS = (
    RoleFamilyDefinition(
        id="ai_ml_engineer",
        label="AI / ML Engineer",
        title_phrases=(
            "ai engineer",
            "artificial intelligence engineer",
            "machine learning engineer",
            "ml engineer",
            "genai engineer",
            "generative ai engineer",
            "llm engineer",
            "nlp engineer",
            "deep learning engineer",
            "prompt engineer",
            "computer vision engineer",
        ),
    ),
    RoleFamilyDefinition(
        id="data_scientist",
        label="Data Scientist",
        title_phrases=(
            "data scientist",
            "applied scientist",
            "research scientist",
            "decision scientist",
        ),
    ),
    RoleFamilyDefinition(
        id="data_engineer",
        label="Data Engineer",
        title_phrases=(
            "data engineer",
            "big data engineer",
            "etl engineer",
            "analytics engineer",
            "bi engineer",
            "business intelligence engineer",
        ),
    ),
    RoleFamilyDefinition(
        id="data_analyst",
        label="Data Analyst",
        title_phrases=(
            "data analyst",
            "business intelligence analyst",
            "bi analyst",
            "analytics analyst",
            "reporting analyst",
        ),
    ),
    RoleFamilyDefinition(
        id="robotics",
        label="Robotics",
        title_phrases=(
            "robotics engineer",
            "robotics software engineer",
            "robotics systems engineer",
            "robotics control engineer",
            "robotics controls engineer",
            "robotics perception engineer",
            "robotics researcher",
            "robotics scientist",
            "autonomy engineer",
            "autonomous systems engineer",
            "mechatronics engineer",
            "motion planning engineer",
            "robot perception engineer",
            "robot control engineer",
            "ros engineer",
        ),
    ),
    RoleFamilyDefinition(
        id="software_engineer",
        label="Software Engineer",
        title_phrases=(
            "software engineer",
            "software developer",
            "backend engineer",
            "backend developer",
            "front end engineer",
            "frontend engineer",
            "full stack engineer",
            "fullstack engineer",
            "application developer",
            "mobile developer",
        ),
    ),
    RoleFamilyDefinition(
        id="cloud_devops_engineer",
        label="Cloud / DevOps Engineer",
        title_phrases=(
            "devops engineer",
            "site reliability engineer",
            "sre",
            "platform engineer",
            "cloud engineer",
            "infrastructure engineer",
            "systems engineer",
        ),
    ),
    RoleFamilyDefinition(
        id="cybersecurity",
        label="Cybersecurity",
        title_phrases=(
            "cybersecurity",
            "cyber security",
            "security engineer",
            "security analyst",
            "soc analyst",
            "information security",
            "penetration tester",
        ),
    ),
    RoleFamilyDefinition(
        id="product_manager",
        label="Product Manager",
        title_phrases=(
            "product manager",
            "product owner",
            "technical product manager",
            "associate product manager",
        ),
    ),
    RoleFamilyDefinition(
        id="business_analyst",
        label="Business Analyst",
        title_phrases=(
            "business analyst",
            "systems analyst",
            "functional analyst",
            "process analyst",
        ),
    ),
    RoleFamilyDefinition(
        id="ux_product_design",
        label="UX / Product Design",
        title_phrases=(
            "ux designer",
            "ui designer",
            "product designer",
            "user experience designer",
            "user interface designer",
        ),
    ),
    RoleFamilyDefinition(
        id="quality_engineer",
        label="Quality Engineer",
        title_phrases=(
            "qa engineer",
            "quality engineer",
            "test engineer",
            "automation tester",
        ),
    ),
    RoleFamilyDefinition(
        id="project_program_manager",
        label="Project / Program Manager",
        title_phrases=(
            "project manager",
            "program manager",
            "programme manager",
            "delivery manager",
            "scrum master",
        ),
    ),
)

OTHER_ROLE = CanonicalRole(
    id="other",
    label="Other / Uncategorized",
    confidence=0.0,
    matched_phrase=None,
)
CUSTOM_ROLE_FAMILY_PREFIX = "custom:"
_CUSTOM_LABEL_ACRONYMS = {
    "ai": "AI",
    "api": "API",
    "bi": "BI",
    "crm": "CRM",
    "devops": "DevOps",
    "llm": "LLM",
    "ml": "ML",
    "nlp": "NLP",
    "qa": "QA",
    "sre": "SRE",
    "ui": "UI",
    "ux": "UX",
}

_ROLE_FAMILY_DEFINITIONS_BY_ID = {
    definition.id: definition for definition in ROLE_FAMILY_DEFINITIONS
}


def canonical_role_family_by_id(family_id: str | None) -> CanonicalRole | None:
    """Return a canonical role family selected by a user."""
    if family_id is None:
        return None
    definition = _ROLE_FAMILY_DEFINITIONS_BY_ID.get(family_id)
    if definition is not None:
        return CanonicalRole(
            id=definition.id,
            label=definition.label,
            confidence=1.0,
            matched_phrase=None,
        )
    if family_id == OTHER_ROLE.id:
        return CanonicalRole(
            id=OTHER_ROLE.id,
            label=OTHER_ROLE.label,
            confidence=1.0,
            matched_phrase=None,
        )
    custom_label = custom_role_family_label(family_id)
    if custom_label is not None:
        return CanonicalRole(
            id=family_id,
            label=custom_label,
            confidence=1.0,
            matched_phrase=None,
        )
    return None


def custom_role_family_id(label: str | None) -> str | None:
    """Return the stable id used for a user-defined role family label."""
    if label is None:
        return None
    slug = re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")
    if not slug:
        return None
    return f"{CUSTOM_ROLE_FAMILY_PREFIX}{slug[:120]}"


def custom_role_family_label(family_id: str | None) -> str | None:
    """Return a readable label for a user-defined canonical role family id."""
    if family_id is None or not family_id.startswith(CUSTOM_ROLE_FAMILY_PREFIX):
        return None
    slug = family_id[len(CUSTOM_ROLE_FAMILY_PREFIX) :].strip("_")
    if not slug or not re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", slug):
        return None
    words = []
    for word in slug.split("_"):
        words.append(_CUSTOM_LABEL_ACRONYMS.get(word, word.capitalize()))
    return " ".join(words)


def role_family_catalog(*, include_other: bool = True) -> tuple[CanonicalRole, ...]:
    """Return all role families available for user selection."""
    roles = tuple(
        CanonicalRole(
            id=definition.id,
            label=definition.label,
            confidence=1.0,
            matched_phrase=None,
        )
        for definition in ROLE_FAMILY_DEFINITIONS
    )
    if include_other:
        return roles + (
            CanonicalRole(
                id=OTHER_ROLE.id,
                label=OTHER_ROLE.label,
                confidence=1.0,
                matched_phrase=None,
            ),
        )
    return roles


def role_family_for_job(job: Job) -> CanonicalRole:
    """Return the user-selected role family for a job, with legacy fallback."""
    selected_role = canonical_role_family_by_id(job.role_family_id)
    if selected_role is not None:
        return selected_role
    return canonical_role_family(job.title)


def canonical_role_family(title: str | None) -> CanonicalRole:
    """Return the canonical role-family match for a raw job title."""
    normalized_title = _normalize_title(title or "")
    if not normalized_title:
        return OTHER_ROLE

    for definition in ROLE_FAMILY_DEFINITIONS:
        for phrase in definition.title_phrases:
            normalized_phrase = _normalize_title(phrase)
            if _contains_phrase(normalized_title, normalized_phrase):
                return CanonicalRole(
                    id=definition.id,
                    label=definition.label,
                    confidence=0.95,
                    matched_phrase=phrase,
                )
    return OTHER_ROLE


def role_family_summaries(
    session: Session,
    *,
    days: int | None = None,
    limit: int | None = 10,
) -> list[RoleFamilySummary]:
    """Return canonical role-family summaries for active jobs."""
    summaries = _build_role_family_summaries(session, days=days)
    if limit is None:
        return summaries
    return summaries[:limit]


def role_family_detail(
    session: Session,
    *,
    family_id: str,
    days: int | None = None,
) -> RoleFamilySummary | None:
    """Return one canonical role-family summary by id."""
    for summary in _build_role_family_summaries(session, days=days):
        if summary.id == family_id:
            return summary
    return None


def top_hiring_companies(
    session: Session,
    *,
    days: int | None = None,
    family_id: str | None = None,
    limit: int = 10,
) -> list[HiringCompanySummary]:
    """Return companies ranked by active canonical job count."""
    active_listings = _active_source_listings(session, days=days)
    listings_by_job_id: dict[int, list[SourceListing]] = {}
    for listing in active_listings:
        if listing.job_id is not None:
            listings_by_job_id.setdefault(listing.job_id, []).append(listing)

    aggregates: dict[str, _HiringCompanyAggregate] = {}
    for job in _active_jobs(session, days=days):
        canonical_role = role_family_for_job(job)
        if family_id is not None and canonical_role.id != family_id:
            continue
        listings = listings_by_job_id.get(job.id or -1, [])
        company_name = _company_name_for_job(job, listings)
        aggregate = aggregates.setdefault(
            company_name,
            _HiringCompanyAggregate(company_name=company_name),
        )
        aggregate.add_job(job, listings)

    rows = [
        aggregate.to_summary()
        for aggregate in aggregates.values()
        if aggregate.job_ids
    ]
    return sorted(
        rows,
        key=lambda row: (
            row.company_name == "UNKNOWN",
            -row.job_count,
            -row.source_listing_count,
            row.company_name.casefold(),
        ),
    )[:limit]


def known_role_family_ids() -> set[str]:
    """Return the role-family ids accepted by the role intelligence API."""
    return {definition.id for definition in ROLE_FAMILY_DEFINITIONS} | {OTHER_ROLE.id}


def _build_role_family_summaries(
    session: Session,
    *,
    days: int | None,
) -> list[RoleFamilySummary]:
    active_listings = _active_source_listings(session, days=days)
    listings_by_job_id: dict[int, list[SourceListing]] = {}
    for listing in active_listings:
        if listing.job_id is not None:
            listings_by_job_id.setdefault(listing.job_id, []).append(listing)

    aggregates: dict[str, _RoleFamilyAggregate] = {}
    for job in _active_jobs(session, days=days):
        canonical_role = role_family_for_job(job)
        aggregate = aggregates.setdefault(
            canonical_role.id,
            _RoleFamilyAggregate(
                role_id=canonical_role.id,
                label=canonical_role.label,
            ),
        )
        aggregate.add_job(job, listings_by_job_id.get(job.id or -1, []))

    summaries = [
        aggregate.to_summary()
        for aggregate in aggregates.values()
        if aggregate.job_ids
    ]
    return sorted(
        summaries,
        key=lambda row: (
            row.id == OTHER_ROLE.id,
            -row.job_count,
            -row.source_listing_count,
            row.label,
        ),
    )


@dataclass
class _RoleFamilyAggregate:
    role_id: str
    label: str
    job_ids: set[int]
    listing_ids: set[int]
    company_names: set[str]
    source_counts: Counter[str]
    skill_counts: Counter[str]
    salary_midpoints: list[float]
    salary_listing_count: int
    example_titles: list[str]

    def __init__(self, *, role_id: str, label: str) -> None:
        self.role_id = role_id
        self.label = label
        self.job_ids = set()
        self.listing_ids = set()
        self.company_names = set()
        self.source_counts = Counter()
        self.skill_counts = Counter()
        self.salary_midpoints = []
        self.salary_listing_count = 0
        self.example_titles = []

    def add_job(self, job: Job, listings: list[SourceListing]) -> None:
        if job.id is not None:
            self.job_ids.add(job.id)
        if job.company is not None:
            self.company_names.add(job.company.name)
        elif listings:
            for listing in listings:
                if listing.source_company_name:
                    self.company_names.add(listing.source_company_name)

        if job.title and job.title not in self.example_titles:
            self.example_titles.append(job.title)

        seen_skills = {
            job_skill.skill.name
            for job_skill in job.job_skills
            if job_skill.skill is not None
        }
        self.skill_counts.update(seen_skills)

        for listing in listings:
            if listing.id is not None:
                self.listing_ids.add(listing.id)
            self.source_counts.update([listing.source])
            annualized_midpoint = annualized_salary_midpoint(
                listing.salary_min,
                listing.salary_max,
                listing.salary_interval,
            )
            if annualized_midpoint is not None:
                self.salary_listing_count += 1
                self.salary_midpoints.append(annualized_midpoint)

    def to_summary(self) -> RoleFamilySummary:
        return RoleFamilySummary(
            id=self.role_id,
            label=self.label,
            job_count=len(self.job_ids),
            source_listing_count=len(self.listing_ids),
            company_count=len(self.company_names),
            salary_listing_count=self.salary_listing_count,
            average_annualized_salary=(
                mean(self.salary_midpoints) if self.salary_midpoints else None
            ),
            top_sources=tuple(self.source_counts.most_common(5)),
            top_skills=tuple(self.skill_counts.most_common(8)),
            example_titles=tuple(self.example_titles[:5]),
        )


@dataclass
class _HiringCompanyAggregate:
    company_name: str
    job_ids: set[int]
    listing_ids: set[int]
    role_counts: Counter[str]
    source_counts: Counter[str]
    latest_seen_at: datetime | None

    def __init__(self, *, company_name: str) -> None:
        self.company_name = company_name
        self.job_ids = set()
        self.listing_ids = set()
        self.role_counts = Counter()
        self.source_counts = Counter()
        self.latest_seen_at = None

    def add_job(self, job: Job, listings: list[SourceListing]) -> None:
        if job.id is not None:
            self.job_ids.add(job.id)
        self.role_counts.update([role_family_for_job(job).label])
        self._update_latest(job.last_seen_at)

        for listing in listings:
            if listing.id is not None:
                self.listing_ids.add(listing.id)
            self.source_counts.update([listing.source])
            self._update_latest(listing.last_seen_at)

    def to_summary(self) -> HiringCompanySummary:
        return HiringCompanySummary(
            company_name=self.company_name,
            job_count=len(self.job_ids),
            source_listing_count=len(self.listing_ids),
            latest_seen_at=self.latest_seen_at,
            top_role_families=tuple(self.role_counts.most_common(5)),
            top_sources=tuple(self.source_counts.most_common(5)),
        )

    def _update_latest(self, value: datetime | None) -> None:
        if value is None:
            return
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        else:
            value = value.astimezone(UTC)
        if self.latest_seen_at is None or value > self.latest_seen_at:
            self.latest_seen_at = value


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


def _company_name_for_job(job: Job, listings: list[SourceListing]) -> str:
    if job.company is not None and job.company.name.strip():
        return job.company.name.strip()
    for listing in listings:
        if listing.source_company_name and listing.source_company_name.strip():
            return listing.source_company_name.strip()
    return "UNKNOWN"


def _cutoff(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _normalize_title(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9+#.]+", " ", value.casefold())
    return re.sub(r"\s+", " ", normalized).strip()


def _contains_phrase(value: str, phrase: str) -> bool:
    if not phrase:
        return False
    return bool(re.search(rf"(^|\s){re.escape(phrase)}($|\s)", value))
