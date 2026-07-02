"""Current-snapshot salary reporting queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from roleradar.storage.models import Job, SourceListing


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


def salary_range_summaries(
    session: Session,
    *,
    days: int | None = None,
) -> list[SalarySummary]:
    """Return salary range summaries for active source listings with salary data."""
    query = (
        select(
            SourceListing.salary_currency,
            SourceListing.salary_interval,
            SourceListing.salary_min,
            SourceListing.salary_max,
        )
        .join(Job, Job.id == SourceListing.job_id)
        .where(
            Job.closed_at.is_(None),
            (
                SourceListing.salary_min.is_not(None)
                | SourceListing.salary_max.is_not(None)
            ),
        )
    )
    if days is not None:
        query = query.where(SourceListing.last_seen_at >= _cutoff(days))

    rows = session.execute(query).all()
    grouped: dict[tuple[str, str], list[tuple[float | None, float | None]]] = {}
    for currency, interval, salary_min, salary_max in rows:
        key = (currency or "UNKNOWN", interval or "unspecified")
        grouped.setdefault(key, []).append((salary_min, salary_max))

    summaries: list[SalarySummary] = []
    for (currency, interval), salaries in grouped.items():
        mins = [value for value, _ in salaries if value is not None]
        maxes = [value for _, value in salaries if value is not None]
        midpoints = [
            midpoint
            for salary_min, salary_max in salaries
            if (midpoint := _range_midpoint(salary_min, salary_max)) is not None
        ]
        summaries.append(
            SalarySummary(
                currency=currency,
                interval=interval,
                posting_count=len(salaries),
                min_salary=min(mins) if mins else None,
                max_salary=max(maxes) if maxes else None,
                average_min_salary=mean(mins) if mins else None,
                average_max_salary=mean(maxes) if maxes else None,
                average_midpoint=mean(midpoints) if midpoints else None,
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


def _range_midpoint(salary_min: float | None, salary_max: float | None) -> float | None:
    if salary_min is not None and salary_max is not None:
        return (salary_min + salary_max) / 2
    return salary_min if salary_min is not None else salary_max


def _cutoff(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)
