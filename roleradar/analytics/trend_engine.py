"""Historical trend analytics built from repeated posting observations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from statistics import mean, median

from sqlalchemy import select
from sqlalchemy.orm import Session

from roleradar.analytics.salary_trends import annualized_salary_midpoint
from roleradar.storage.models import (
    Company,
    Job,
    JobSkill,
    PostingObservation,
    Skill,
    SourceListing,
)
from roleradar.storage.repositories import normalize_text


@dataclass(frozen=True)
class WeeklyCount:
    """Weekly active posting count for a skill, including week-over-week movement."""

    week_start: date
    count: int
    previous_count: int | None
    delta: int | None
    delta_percent: float | None


@dataclass(frozen=True)
class WeeklySalary:
    """Weekly annualized salary midpoint for a role family."""

    week_start: date
    posting_count: int
    average_annualized_midpoint: float | None


@dataclass(frozen=True)
class WeeklyVelocity:
    """Weekly new and closed posting counts."""

    week_start: date
    new_posting_count: int
    closed_posting_count: int


@dataclass(frozen=True)
class WeeklyCompanyVelocity:
    """Weekly new posting count for one company."""

    week_start: date
    company_id: int | None
    company_name: str
    new_posting_count: int


@dataclass(frozen=True)
class TimeToCloseStats:
    """Distribution of days between first seen and closed timestamps."""

    posting_count: int
    median_days: float | None
    p75_days: float | None


def skill_demand_over_time(
    session: Session,
    *,
    skill_name: str,
    weeks: int = 12,
    as_of: datetime | None = None,
) -> list[WeeklyCount]:
    """Count active canonical jobs mentioning a skill per ISO week."""
    week_starts = _week_starts(weeks=weeks, as_of=as_of)
    observed_job_ids_by_week: dict[date, set[int]] = {
        week_start: set() for week_start in week_starts
    }
    skill_key = normalize_text(skill_name)

    query = (
        select(PostingObservation, SourceListing, Job, Skill)
        .join(SourceListing, SourceListing.id == PostingObservation.source_listing_id)
        .join(Job, Job.id == SourceListing.job_id)
        .join(JobSkill, JobSkill.job_id == Job.id)
        .join(Skill, Skill.id == JobSkill.skill_id)
        .where(
            PostingObservation.observed_at >= _window_start(week_starts),
            PostingObservation.observed_at < _window_end(week_starts),
            PostingObservation.is_active.is_(True),
            Skill.normalized_name == skill_key,
        )
    )

    for observation, _listing, job, _skill in session.execute(query).all():
        if job.id is None:
            continue
        week_start = _iso_week_start(observation.observed_at)
        if week_start in observed_job_ids_by_week:
            observed_job_ids_by_week[week_start].add(job.id)

    counts = [
        (week_start, len(observed_job_ids_by_week[week_start]))
        for week_start in week_starts
    ]
    return _with_weekly_deltas(counts)


def salary_trend_over_time(
    session: Session,
    *,
    family_id: str,
    weeks: int = 12,
    as_of: datetime | None = None,
) -> list[WeeklySalary]:
    """Average annualized salary midpoint per week for a role family."""
    week_starts = _week_starts(weeks=weeks, as_of=as_of)
    salaries_by_week: dict[date, dict[int, float]] = {
        week_start: {} for week_start in week_starts
    }

    query = (
        select(PostingObservation, SourceListing, Job)
        .join(SourceListing, SourceListing.id == PostingObservation.source_listing_id)
        .join(Job, Job.id == SourceListing.job_id)
        .where(
            PostingObservation.observed_at >= _window_start(week_starts),
            PostingObservation.observed_at < _window_end(week_starts),
            PostingObservation.is_active.is_(True),
            Job.role_family_id == family_id,
        )
    )

    for observation, listing, job in session.execute(query).all():
        if job.id is None:
            continue
        midpoint = annualized_salary_midpoint(
            listing.salary_min,
            listing.salary_max,
            listing.salary_interval,
        )
        if midpoint is None:
            continue
        week_start = _iso_week_start(observation.observed_at)
        if week_start in salaries_by_week:
            salaries_by_week[week_start][job.id] = midpoint

    return [
        WeeklySalary(
            week_start=week_start,
            posting_count=len(salaries_by_week[week_start]),
            average_annualized_midpoint=(
                mean(salaries_by_week[week_start].values())
                if salaries_by_week[week_start]
                else None
            ),
        )
        for week_start in week_starts
    ]


def posting_velocity(
    session: Session,
    *,
    family_id: str | None = None,
    weeks: int = 12,
    as_of: datetime | None = None,
) -> list[WeeklyVelocity]:
    """Return new postings and closures per ISO week."""
    week_starts = _week_starts(weeks=weeks, as_of=as_of)
    new_counts: dict[date, int] = {week_start: 0 for week_start in week_starts}
    closed_counts: dict[date, int] = {week_start: 0 for week_start in week_starts}

    query = select(Job)
    if family_id is not None:
        query = query.where(Job.role_family_id == family_id)

    for job in session.scalars(query).all():
        first_seen_week = _iso_week_start(job.first_seen_at)
        if first_seen_week in new_counts:
            new_counts[first_seen_week] += 1
        if job.closed_at is not None:
            closed_week = _iso_week_start(job.closed_at)
            if closed_week in closed_counts:
                closed_counts[closed_week] += 1

    return [
        WeeklyVelocity(
            week_start=week_start,
            new_posting_count=new_counts[week_start],
            closed_posting_count=closed_counts[week_start],
        )
        for week_start in week_starts
    ]


def company_hiring_velocity(
    session: Session,
    *,
    family_id: str | None = None,
    weeks: int = 12,
    as_of: datetime | None = None,
    limit: int | None = None,
) -> list[WeeklyCompanyVelocity]:
    """Return weekly new posting counts grouped by canonical company."""
    week_starts = _week_starts(weeks=weeks, as_of=as_of)
    counts: dict[tuple[date, int | None, str], int] = defaultdict(int)

    query = (
        select(Job, Company)
        .outerjoin(Company, Company.id == Job.company_id)
        .where(
            Job.first_seen_at >= _window_start(week_starts),
            Job.first_seen_at < _window_end(week_starts),
        )
    )
    if family_id is not None:
        query = query.where(Job.role_family_id == family_id)
    for job, company in session.execute(query).all():
        week_start = _iso_week_start(job.first_seen_at)
        company_name = company.name if company is not None else "UNKNOWN"
        counts[(week_start, job.company_id, company_name)] += 1

    rows = [
        WeeklyCompanyVelocity(
            week_start=week_start,
            company_id=company_id,
            company_name=company_name,
            new_posting_count=new_posting_count,
        )
        for (week_start, company_id, company_name), new_posting_count in counts.items()
    ]
    rows = sorted(
        rows,
        key=lambda row: (row.week_start, -row.new_posting_count, row.company_name),
    )
    if limit is None:
        return rows
    return rows[:limit]


def time_to_close(
    session: Session,
    *,
    family_id: str | None = None,
) -> TimeToCloseStats:
    """Return median and P75 days from first seen to closed for closed jobs."""
    query = select(Job).where(Job.closed_at.is_not(None))
    if family_id is not None:
        query = query.where(Job.role_family_id == family_id)

    durations = sorted(
        (job.closed_at - job.first_seen_at).total_seconds() / 86400
        for job in session.scalars(query).all()
        if job.closed_at is not None and job.first_seen_at is not None
    )
    return TimeToCloseStats(
        posting_count=len(durations),
        median_days=median(durations) if durations else None,
        p75_days=_percentile(durations, 0.75) if durations else None,
    )


def _with_weekly_deltas(counts: list[tuple[date, int]]) -> list[WeeklyCount]:
    rows: list[WeeklyCount] = []
    previous_count: int | None = None
    for week_start, count in counts:
        delta = None if previous_count is None else count - previous_count
        delta_percent = None
        if previous_count not in (None, 0):
            delta_percent = delta / previous_count
        rows.append(
            WeeklyCount(
                week_start=week_start,
                count=count,
                previous_count=previous_count,
                delta=delta,
                delta_percent=delta_percent,
            )
        )
        previous_count = count
    return rows


def _week_starts(*, weeks: int, as_of: datetime | None) -> list[date]:
    if weeks < 1:
        raise ValueError("weeks must be at least 1")
    anchor = as_of or datetime.now(UTC)
    current_week_start = _iso_week_start(anchor)
    first_week_start = current_week_start - timedelta(weeks=weeks - 1)
    return [first_week_start + timedelta(weeks=offset) for offset in range(weeks)]


def _window_start(week_starts: list[date]) -> datetime:
    return datetime.combine(week_starts[0], time.min, tzinfo=UTC)


def _window_end(week_starts: list[date]) -> datetime:
    return datetime.combine(week_starts[-1] + timedelta(weeks=1), time.min, tzinfo=UTC)


def _iso_week_start(value: datetime) -> date:
    return value.date() - timedelta(days=value.date().isoweekday() - 1)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ValueError("values must not be empty")
    if len(values) == 1:
        return values[0]
    index = (len(values) - 1) * percentile
    lower_index = int(index)
    upper_index = min(lower_index + 1, len(values) - 1)
    weight = index - lower_index
    return values[lower_index] * (1 - weight) + values[upper_index] * weight
