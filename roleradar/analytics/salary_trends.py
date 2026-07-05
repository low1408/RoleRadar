"""Current-snapshot salary reporting queries."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median, quantiles

from sqlalchemy.orm import Session

from roleradar.analytics.queries import (
    active_source_listings as _active_source_listings,
)
from roleradar.analytics.skill_trends import DEFAULT_ROLE_KEYWORDS
from roleradar.storage.models import SourceListing


@dataclass(frozen=True)
class SalarySummary:
    """Summary of employer-provided salary ranges."""

    currency: str
    interval: str
    posting_count: int
    min_salary: float | None
    max_salary: float | None
    average_min_salary: float | None
    average_max_salary: float | None
    average_midpoint: float | None
    average_annualized_midpoint: float | None
    p25_annualized_midpoint: float | None
    median_annualized_midpoint: float | None
    p75_annualized_midpoint: float | None
    closed_range_count: int


@dataclass(frozen=True)
class SalaryCoverage:
    """Salary disclosure coverage for a listing cohort."""

    group: str
    total_posting_count: int
    salary_posting_count: int
    disclosure_rate: float


@dataclass(frozen=True)
class SalarySegmentSummary:
    """Annualized salary midpoint summary for a named segment."""

    segment_type: str
    segment: str
    posting_count: int
    average_annualized_midpoint: float | None
    p25_annualized_midpoint: float | None
    median_annualized_midpoint: float | None
    p75_annualized_midpoint: float | None


@dataclass(frozen=True)
class SalaryListing:
    """One salary-bearing listing ranked by comparable annualized midpoint."""

    company_name: str
    title: str
    source: str
    currency: str
    interval: str
    salary_min: float | None
    salary_max: float | None
    annualized_midpoint: float
    source_url: str | None


def salary_range_summaries(
    session: Session,
    *,
    days: int | None = None,
) -> list[SalarySummary]:
    """Return salary range summaries for active source listings with salary data."""
    grouped: dict[tuple[str, str], list[SourceListing]] = {}
    for listing in _active_source_listings(session, days=days):
        if not _has_salary(listing):
            continue
        key = (
            listing.salary_currency or "UNKNOWN",
            listing.salary_interval or "unspecified",
        )
        grouped.setdefault(key, []).append(listing)

    summaries: list[SalarySummary] = []
    for (currency, interval), listings in grouped.items():
        mins = [
            listing.salary_min for listing in listings if listing.salary_min is not None
        ]
        maxes = [
            listing.salary_max for listing in listings if listing.salary_max is not None
        ]
        midpoints = [
            midpoint
            for listing in listings
            if (
                midpoint := _closed_range_midpoint(
                    listing.salary_min, listing.salary_max
                )
            )
            is not None
        ]
        annualized_midpoints = [
            annualized
            for listing in listings
            if (
                annualized := _annualized_midpoint(
                    listing.salary_min,
                    listing.salary_max,
                    listing.salary_interval,
                )
            )
            is not None
        ]
        summaries.append(
            SalarySummary(
                currency=currency,
                interval=interval,
                posting_count=len(listings),
                min_salary=min(mins) if mins else None,
                max_salary=max(maxes) if maxes else None,
                average_min_salary=mean(mins) if mins else None,
                average_max_salary=mean(maxes) if maxes else None,
                average_midpoint=mean(midpoints) if midpoints else None,
                average_annualized_midpoint=(
                    mean(annualized_midpoints) if annualized_midpoints else None
                ),
                p25_annualized_midpoint=_percentile(
                    annualized_midpoints,
                    quartile=1,
                ),
                median_annualized_midpoint=(
                    median(annualized_midpoints) if annualized_midpoints else None
                ),
                p75_annualized_midpoint=_percentile(
                    annualized_midpoints,
                    quartile=3,
                ),
                closed_range_count=len(midpoints),
            )
        )

    return sorted(
        summaries,
        key=lambda summary: (
            summary.currency,
            summary.interval,
            -summary.posting_count,
        ),
    )


def salary_coverage(
    session: Session,
    *,
    days: int | None = None,
) -> SalaryCoverage:
    """Return overall employer-provided salary disclosure coverage."""
    listings = _active_source_listings(session, days=days)
    salary_count = sum(1 for listing in listings if _has_salary(listing))
    return _coverage("all", len(listings), salary_count)


def salary_coverage_by_source(
    session: Session,
    *,
    days: int | None = None,
) -> list[SalaryCoverage]:
    """Return salary disclosure coverage grouped by source."""
    grouped: dict[str, list[SourceListing]] = {}
    for listing in _active_source_listings(session, days=days):
        grouped.setdefault(listing.source, []).append(listing)

    return [
        _coverage(
            source,
            len(listings),
            sum(1 for listing in listings if _has_salary(listing)),
        )
        for source, listings in sorted(grouped.items())
    ]


def salary_by_source(
    session: Session,
    *,
    days: int | None = None,
    limit: int = 10,
) -> list[SalarySegmentSummary]:
    """Return annualized salary midpoint summaries grouped by source."""
    return _salary_segments(
        session,
        days=days,
        limit=limit,
        segment_type="source",
        grouper=lambda listing: [listing.source],
    )


def salary_by_company(
    session: Session,
    *,
    days: int | None = None,
    limit: int = 10,
) -> list[SalarySegmentSummary]:
    """Return annualized salary midpoint summaries grouped by company."""
    return _salary_segments(
        session,
        days=days,
        limit=limit,
        segment_type="company",
        grouper=lambda listing: [
            (
                listing.job.company.name
                if listing.job is not None and listing.job.company is not None
                else listing.source_company_name or "UNKNOWN"
            )
        ],
    )


def salary_by_skill(
    session: Session,
    *,
    days: int | None = None,
    limit: int = 10,
) -> list[SalarySegmentSummary]:
    """Return annualized salary midpoint summaries grouped by extracted skill."""

    def skill_names(listing: SourceListing) -> list[str]:
        if listing.job is None:
            return []
        return [
            job_skill.skill.name
            for job_skill in listing.job.job_skills
            if job_skill.skill is not None
        ]

    return _salary_segments(
        session,
        days=days,
        limit=limit,
        segment_type="skill",
        grouper=skill_names,
    )


def salary_by_role_keyword(
    session: Session,
    *,
    days: int | None = None,
    role_keywords: tuple[str, ...] = DEFAULT_ROLE_KEYWORDS,
    limit: int = 10,
) -> list[SalarySegmentSummary]:
    """Return annualized salary midpoint summaries grouped by role/title keyword."""
    normalized_keywords = {
        keyword: " ".join(keyword.strip().casefold().split())
        for keyword in role_keywords
    }

    def matching_keywords(listing: SourceListing) -> list[str]:
        title = listing.job.normalized_title if listing.job is not None else ""
        return [
            keyword
            for keyword, normalized_keyword in normalized_keywords.items()
            if normalized_keyword and normalized_keyword in title
        ]

    return _salary_segments(
        session,
        days=days,
        limit=limit,
        segment_type="role_keyword",
        grouper=matching_keywords,
    )


def top_salary_listings(
    session: Session,
    *,
    days: int | None = None,
    limit: int = 10,
) -> list[SalaryListing]:
    """Return active listings ranked by comparable annualized midpoint."""
    ranked: list[SalaryListing] = []
    for listing in _active_source_listings(session, days=days):
        annualized_midpoint = _annualized_midpoint(
            listing.salary_min,
            listing.salary_max,
            listing.salary_interval,
        )
        if annualized_midpoint is None:
            continue
        job = listing.job
        ranked.append(
            SalaryListing(
                company_name=(
                    job.company.name
                    if job is not None and job.company is not None
                    else listing.source_company_name or "UNKNOWN"
                ),
                title=(
                    job.title
                    if job is not None
                    else listing.source_title or "Untitled role"
                ),
                source=listing.source,
                currency=listing.salary_currency or "UNKNOWN",
                interval=listing.salary_interval or "unspecified",
                salary_min=listing.salary_min,
                salary_max=listing.salary_max,
                annualized_midpoint=annualized_midpoint,
                source_url=listing.source_url or listing.canonical_url,
            )
        )
    return sorted(
        ranked,
        key=lambda listing: listing.annualized_midpoint,
        reverse=True,
    )[:limit]


def annualized_salary_midpoint(
    salary_min: float | None,
    salary_max: float | None,
    interval: str | None,
) -> float | None:
    """Return comparable annualized midpoint for closed ranges only."""
    return _annualized_midpoint(salary_min, salary_max, interval)


def _salary_segments(
    session: Session,
    *,
    days: int | None,
    limit: int,
    segment_type: str,
    grouper,
) -> list[SalarySegmentSummary]:
    grouped: dict[str, list[float]] = {}
    for listing in _active_source_listings(session, days=days):
        annualized_midpoint = _annualized_midpoint(
            listing.salary_min,
            listing.salary_max,
            listing.salary_interval,
        )
        if annualized_midpoint is None:
            continue
        for segment in grouper(listing):
            grouped.setdefault(segment, []).append(annualized_midpoint)

    summaries = [
        SalarySegmentSummary(
            segment_type=segment_type,
            segment=segment,
            posting_count=len(values),
            average_annualized_midpoint=mean(values) if values else None,
            p25_annualized_midpoint=_percentile(values, quartile=1),
            median_annualized_midpoint=median(values) if values else None,
            p75_annualized_midpoint=_percentile(values, quartile=3),
        )
        for segment, values in grouped.items()
    ]
    return sorted(
        summaries,
        key=lambda summary: (
            -(summary.average_annualized_midpoint or 0),
            -summary.posting_count,
            summary.segment,
        ),
    )[:limit]


def _coverage(group: str, total_count: int, salary_count: int) -> SalaryCoverage:
    return SalaryCoverage(
        group=group,
        total_posting_count=total_count,
        salary_posting_count=salary_count,
        disclosure_rate=salary_count / total_count if total_count else 0.0,
    )


def _has_salary(listing: SourceListing) -> bool:
    return listing.salary_min is not None or listing.salary_max is not None


def _closed_range_midpoint(
    salary_min: float | None,
    salary_max: float | None,
) -> float | None:
    if salary_min is None or salary_max is None:
        return None
    return (salary_min + salary_max) / 2


def _annualized_midpoint(
    salary_min: float | None,
    salary_max: float | None,
    interval: str | None,
) -> float | None:
    midpoint = _closed_range_midpoint(salary_min, salary_max)
    multiplier = _annualization_multiplier(interval)
    if midpoint is None or multiplier is None:
        return None
    return midpoint * multiplier


def _annualization_multiplier(interval: str | None) -> float | None:
    if interval is None:
        return None
    normalized = interval.strip().casefold()
    if normalized in {"year", "yearly", "annual", "annually", "per year"}:
        return 1
    if normalized in {"month", "monthly", "per month"}:
        return 12
    if normalized in {"week", "weekly", "per week"}:
        return 52
    if normalized in {"day", "daily", "per day"}:
        return 260
    if normalized in {"hour", "hourly", "per hour"}:
        return 2080
    return None


def _percentile(values: list[float], *, quartile: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return quantiles(sorted(values), n=4, method="inclusive")[quartile - 1]
