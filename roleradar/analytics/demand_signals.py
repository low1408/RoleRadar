"""Company hiring demand signals built from source listings and observations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from roleradar.analytics.queries import active_source_listings, cutoff
from roleradar.analytics.role_intelligence import role_family_for_job
from roleradar.storage.models import Job, SourceListing


@dataclass(frozen=True)
class ActiveListingsSummary:
    """Overall active and newly observed listing counts."""

    active_listing_count: int
    new_listing_count_7d: int
    new_listing_count_30d: int
    company_count: int
    role_family_count: int


@dataclass(frozen=True)
class CompanyDemandSignal:
    """Hiring demand signal for one company."""

    company_name: str
    active_listing_count: int
    new_listing_count_7d: int
    new_listing_count_30d: int
    previous_new_listing_count_7d: int
    week_over_week_new_listing_delta: int
    role_family_count: int
    top_role_families: tuple[tuple[str, int], ...]
    salary_disclosure_rate: float


@dataclass(frozen=True)
class CompanyRoleFamilyDemand:
    """Active listing count for one company and role-family pair."""

    company_name: str
    role_family_id: str
    role_family_label: str
    active_listing_count: int


@dataclass(frozen=True)
class NewListingsByCompany:
    """New source listings first observed within a rolling window."""

    company_name: str
    new_listing_count: int


@dataclass(frozen=True)
class CompanyHiringBreadth:
    """Number of distinct role families represented by active company listings."""

    company_name: str
    role_family_count: int


def active_listings_summary(session: Session) -> ActiveListingsSummary:
    """Return global active listing and recent-new listing counts."""
    listings = active_source_listings(session)
    companies = {_company_name(listing) for listing in listings}
    role_families = {
        role_family_for_job(listing.job).id
        for listing in listings
        if listing.job is not None
    }
    return ActiveListingsSummary(
        active_listing_count=len(listings),
        new_listing_count_7d=_new_listing_count(listings, days=7),
        new_listing_count_30d=_new_listing_count(listings, days=30),
        company_count=len(companies),
        role_family_count=len(role_families),
    )


def active_listings_by_company(
    session: Session,
    *,
    limit: int = 10,
) -> list[CompanyDemandSignal]:
    """Return companies ranked by active listing volume."""
    active_listings = active_source_listings(session)
    previous_window_listings = _source_listings_first_seen_between(
        session,
        newer_than_days=14,
        older_than_days=7,
    )
    previous_counts = Counter(
        _company_name(listing) for listing in previous_window_listings
    )

    aggregates: dict[str, _CompanyDemandAggregate] = {}
    for listing in active_listings:
        company_name = _company_name(listing)
        aggregate = aggregates.setdefault(
            company_name,
            _CompanyDemandAggregate(company_name=company_name),
        )
        aggregate.add_listing(listing)

    rows = [
        aggregate.to_signal(previous_new_listing_count_7d=previous_counts[name])
        for name, aggregate in aggregates.items()
    ]
    return sorted(
        rows,
        key=lambda row: (
            row.company_name == "UNKNOWN",
            -row.active_listing_count,
            -row.new_listing_count_7d,
            -row.role_family_count,
            row.company_name.casefold(),
        ),
    )[:limit]


def active_listings_by_company_and_role_family(
    session: Session,
    *,
    limit: int = 50,
) -> list[CompanyRoleFamilyDemand]:
    """Return active listing counts for company and role-family pairs."""
    counts: Counter[tuple[str, str, str]] = Counter()
    for listing in active_source_listings(session):
        if listing.job is None:
            continue
        role = role_family_for_job(listing.job)
        counts[(_company_name(listing), role.id, role.label)] += 1

    rows = [
        CompanyRoleFamilyDemand(
            company_name=company_name,
            role_family_id=role_family_id,
            role_family_label=role_family_label,
            active_listing_count=count,
        )
        for (company_name, role_family_id, role_family_label), count in counts.items()
    ]
    return sorted(
        rows,
        key=lambda row: (
            row.company_name == "UNKNOWN",
            -row.active_listing_count,
            row.company_name.casefold(),
            row.role_family_label,
        ),
    )[:limit]


def new_listings_by_company(
    session: Session,
    *,
    days: int = 7,
    limit: int = 10,
) -> list[NewListingsByCompany]:
    """Return new listings by company using source-listing first_seen_at."""
    listings = _source_listings_first_seen_since(session, days=days)
    counts = Counter(_company_name(listing) for listing in listings)
    rows = [
        NewListingsByCompany(
            company_name=company_name,
            new_listing_count=count,
        )
        for company_name, count in counts.items()
    ]
    return sorted(
        rows,
        key=lambda row: (
            row.company_name == "UNKNOWN",
            -row.new_listing_count,
            row.company_name.casefold(),
        ),
    )[:limit]


def company_hiring_breadth(
    session: Session,
    *,
    limit: int = 10,
) -> list[CompanyHiringBreadth]:
    """Return companies ranked by distinct active role-family count."""
    role_families_by_company: dict[str, set[str]] = {}
    for listing in active_source_listings(session):
        if listing.job is None:
            continue
        role_families_by_company.setdefault(_company_name(listing), set()).add(
            role_family_for_job(listing.job).id
        )
    rows = [
        CompanyHiringBreadth(
            company_name=company_name,
            role_family_count=len(role_family_ids),
        )
        for company_name, role_family_ids in role_families_by_company.items()
    ]
    return sorted(
        rows,
        key=lambda row: (
            row.company_name == "UNKNOWN",
            -row.role_family_count,
            row.company_name.casefold(),
        ),
    )[:limit]


@dataclass
class _CompanyDemandAggregate:
    company_name: str
    active_listing_ids: set[int]
    role_counts: Counter[str]
    salary_listing_count: int
    new_listing_count_7d: int
    new_listing_count_30d: int

    def __init__(self, *, company_name: str) -> None:
        self.company_name = company_name
        self.active_listing_ids = set()
        self.role_counts = Counter()
        self.salary_listing_count = 0
        self.new_listing_count_7d = 0
        self.new_listing_count_30d = 0

    def add_listing(self, listing: SourceListing) -> None:
        if listing.id is not None:
            self.active_listing_ids.add(listing.id)
        if listing.job is not None:
            self.role_counts.update([role_family_for_job(listing.job).label])
        if listing.salary_min is not None or listing.salary_max is not None:
            self.salary_listing_count += 1
        if _as_utc(listing.first_seen_at) >= cutoff(7):
            self.new_listing_count_7d += 1
        if _as_utc(listing.first_seen_at) >= cutoff(30):
            self.new_listing_count_30d += 1

    def to_signal(self, *, previous_new_listing_count_7d: int) -> CompanyDemandSignal:
        active_listing_count = len(self.active_listing_ids)
        return CompanyDemandSignal(
            company_name=self.company_name,
            active_listing_count=active_listing_count,
            new_listing_count_7d=self.new_listing_count_7d,
            new_listing_count_30d=self.new_listing_count_30d,
            previous_new_listing_count_7d=previous_new_listing_count_7d,
            week_over_week_new_listing_delta=(
                self.new_listing_count_7d - previous_new_listing_count_7d
            ),
            role_family_count=len(self.role_counts),
            top_role_families=tuple(self.role_counts.most_common(5)),
            salary_disclosure_rate=(
                self.salary_listing_count / active_listing_count
                if active_listing_count
                else 0.0
            ),
        )


def _source_listings_first_seen_since(
    session: Session,
    *,
    days: int,
) -> list[SourceListing]:
    return list(
        session.scalars(
            select(SourceListing)
            .join(Job, Job.id == SourceListing.job_id)
            .where(SourceListing.first_seen_at >= cutoff(days))
        )
        .unique()
        .all()
    )


def _source_listings_first_seen_between(
    session: Session,
    *,
    newer_than_days: int,
    older_than_days: int,
) -> list[SourceListing]:
    return list(
        session.scalars(
            select(SourceListing)
            .join(Job, Job.id == SourceListing.job_id)
            .where(
                SourceListing.first_seen_at >= cutoff(newer_than_days),
                SourceListing.first_seen_at < cutoff(older_than_days),
            )
        )
        .unique()
        .all()
    )


def _new_listing_count(listings: list[SourceListing], *, days: int) -> int:
    threshold = cutoff(days)
    return sum(1 for listing in listings if _as_utc(listing.first_seen_at) >= threshold)


def _company_name(listing: SourceListing) -> str:
    if listing.job is not None and listing.job.company is not None:
        return listing.job.company.name
    return listing.source_company_name or "UNKNOWN"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
