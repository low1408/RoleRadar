"""Job ingestion orchestration."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from roleradar.analytics.skill_matcher import extract_and_persist_job_skills
from roleradar.ingestion.normalize_jobs import (
    NormalizedJob,
    normalize_adzuna_posting,
    normalize_careers_gov_posting,
    normalize_greenhouse_posting,
    normalize_jobstreet_posting,
    normalize_lever_posting,
)
from roleradar.sources.adzuna import AdzunaClient
from roleradar.sources.base import JobSourceClient
from roleradar.sources.careers_gov import CareersGovClient
from roleradar.sources.greenhouse import GreenhouseClient
from roleradar.sources.jobstreet import DEFAULT_SITE_KEY, JobstreetClient
from roleradar.sources.lever import LeverClient
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.models import (
    IngestionRun,
    Job,
    PostingObservation,
    SourceListing,
)
from roleradar.storage.repositories import IngestionRunRepository, JobRepository

SUPPORTED_SOURCES = ("adzuna", "careers_gov", "greenhouse", "jobstreet", "lever")
QUERY_SOURCES = {"adzuna", "careers_gov", "jobstreet"}
CONSECUTIVE_MISSES_TO_CLOSE = 3


@dataclass(frozen=True)
class TargetCompany:
    """One configured ingestion target."""

    company_name: str
    source: str
    board_token_or_site: str
    enabled: bool = True
    notes: str | None = None


@dataclass(frozen=True)
class IngestionResult:
    """Summary of one ingestion command."""

    source: str
    targets_seen: int
    targets_ingested: int
    targets_failed: int
    jobs_seen: int
    source_listings_upserted: int
    observations_created: int
    job_skills_extracted: int
    duplicate_candidates: int
    error_message: str | None = None


@dataclass(frozen=True)
class SourceHandler:
    """Fetch and normalize jobs for one supported source."""

    client: JobSourceClient
    source_name: str

    def normalize(
        self,
        target: TargetCompany,
        postings: Iterable[dict],
    ) -> list[NormalizedJob]:
        if self.source_name == "lever":
            return [
                normalize_lever_posting(
                    posting=posting,
                    company_name=target.company_name,
                    board_token_or_site=target.board_token_or_site,
                )
                for posting in postings
            ]
        if self.source_name == "greenhouse":
            return [
                normalize_greenhouse_posting(
                    posting=posting,
                    company_name=target.company_name,
                    board_token_or_site=target.board_token_or_site,
                )
                for posting in postings
            ]
        raise ValueError(f"Unsupported ingestion source: {self.source_name}")


def read_target_companies(file_path: str | Path) -> list[TargetCompany]:
    """Read target companies CSV file."""
    path = Path(file_path)
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [_parse_target(row) for row in reader]


def ingest_jobs(
    *,
    database_url: str,
    source: str,
    targets_file: str | Path | None = None,
    query: str | None = None,
    location: str | None = None,
    country: str = "sg",
    results_per_page: int = 20,
    max_pages: int = 1,
    role_family_id: str | None = None,
    sqlite_wal: bool = True,
    sqlite_busy_timeout_ms: int = 5000,
    careers_gov_timeout_seconds: float = 20.0,
    careers_gov_throttle_seconds: float = 1.0,
    jobstreet_site_key: str = DEFAULT_SITE_KEY,
    jobstreet_timeout_seconds: float = 20.0,
    adzuna_app_id: str | None = None,
    adzuna_app_key: str | None = None,
    adzuna_client: AdzunaClient | None = None,
    careers_gov_client: CareersGovClient | None = None,
    jobstreet_client: JobstreetClient | None = None,
    lever_client: LeverClient | None = None,
    greenhouse_client: GreenhouseClient | None = None,
) -> IngestionResult:
    """Ingest jobs from a supported source."""
    if source not in SUPPORTED_SOURCES:
        raise ValueError(f"Unsupported ingestion source: {source}")

    targets = _targets_for_source(
        source=source,
        targets_file=targets_file,
    )
    handler = (
        None
        if source in {"adzuna", "careers_gov", "jobstreet"}
        else _source_handler(
            source=source,
            lever_client=lever_client,
            greenhouse_client=greenhouse_client,
        )
    )
    engine = create_database_engine(
        database_url,
        sqlite_wal=sqlite_wal,
        sqlite_busy_timeout_ms=sqlite_busy_timeout_ms,
    )
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    counters = _Counters()

    with session_factory() as session:
        run_repo = IngestionRunRepository(session)
        job_repo = JobRepository(session)
        run = run_repo.create(
            source=source,
            parameters={
                "targets_file": str(targets_file) if targets_file else None,
                "query": query,
                "location": location,
                "country": country,
                "results_per_page": results_per_page,
                "max_pages": max_pages,
                "role_family_id": role_family_id,
                "jobstreet_site_key": (
                    jobstreet_site_key if source == "jobstreet" else None
                ),
            },
        )

        if source == "adzuna":
            counters.targets_seen = 1
            _ingest_adzuna(
                counters=counters,
                run=run,
                job_repo=job_repo,
                query=query,
                location=location,
                country=country,
                results_per_page=results_per_page,
                role_family_id=role_family_id,
                adzuna_app_id=adzuna_app_id,
                adzuna_app_key=adzuna_app_key,
                adzuna_client=adzuna_client,
            )
        elif source == "careers_gov":
            counters.targets_seen = 1
            _ingest_careers_gov(
                counters=counters,
                run=run,
                job_repo=job_repo,
                query=query,
                results_per_page=results_per_page,
                max_pages=max_pages,
                timeout_seconds=careers_gov_timeout_seconds,
            throttle_seconds=careers_gov_throttle_seconds,
            role_family_id=role_family_id,
                careers_gov_client=careers_gov_client,
            )
        elif source == "jobstreet":
            counters.targets_seen = 1
            _ingest_jobstreet(
                counters=counters,
                run=run,
                job_repo=job_repo,
                query=query,
                location=location,
                max_pages=max_pages,
                site_key=jobstreet_site_key,
            timeout_seconds=jobstreet_timeout_seconds,
            role_family_id=role_family_id,
                jobstreet_client=jobstreet_client,
            )
        else:
            counters.targets_seen = len(targets)
            _ingest_target_boards(
                counters=counters,
                run=run,
                job_repo=job_repo,
                handler=handler,
            targets=targets,
            role_family_id=role_family_id,
            )

        if source in QUERY_SOURCES and query and counters.targets_ingested > 0:
            missing_observations = _record_missing_query_source_listings(
                session=session,
                job_repo=job_repo,
                run=run,
                source=source,
                query=query,
                current_source_listing_ids=counters.current_source_listing_ids,
            )
            counters.observations_created += missing_observations

        run_status = (
            "completed" if counters.targets_failed == 0 else "completed_with_errors"
        )
        run_repo.complete(run, status=run_status)
        session.commit()

    return IngestionResult(
        source=source,
        error_message=run.error_message,
        **counters.as_result_kwargs(),
    )


@dataclass
class _Counters:
    targets_seen: int = 0
    targets_ingested: int = 0
    targets_failed: int = 0
    jobs_seen: int = 0
    source_listings_upserted: int = 0
    observations_created: int = 0
    job_skills_extracted: int = 0
    duplicate_candidates: int = 0
    current_source_listing_ids: set[int] | None = None

    def add_persisted(self, values: tuple[int, int, int, int, int, set[int]]) -> None:
        seen, upserted, observations, skills, candidates, listing_ids = values
        self.jobs_seen += seen
        self.source_listings_upserted += upserted
        self.observations_created += observations
        self.job_skills_extracted += skills
        self.duplicate_candidates += candidates
        if self.current_source_listing_ids is None:
            self.current_source_listing_ids = set()
        self.current_source_listing_ids.update(listing_ids)

    def as_result_kwargs(self) -> dict[str, int]:
        return {
            "targets_seen": self.targets_seen,
            "targets_ingested": self.targets_ingested,
            "targets_failed": self.targets_failed,
            "jobs_seen": self.jobs_seen,
            "source_listings_upserted": self.source_listings_upserted,
            "observations_created": self.observations_created,
            "job_skills_extracted": self.job_skills_extracted,
            "duplicate_candidates": self.duplicate_candidates,
        }


def _ingest_adzuna(
    *,
    counters: _Counters,
    run: IngestionRun,
    job_repo: JobRepository,
    query: str | None,
    location: str | None,
    country: str,
    results_per_page: int,
    role_family_id: str | None,
    adzuna_app_id: str | None,
    adzuna_app_key: str | None,
    adzuna_client: AdzunaClient | None,
) -> None:
    try:
        normalized_jobs = _fetch_adzuna_jobs(
            query=query,
            location=location,
            country=country,
            results_per_page=results_per_page,
            adzuna_app_id=adzuna_app_id,
            adzuna_app_key=adzuna_app_key,
            adzuna_client=adzuna_client,
        )
    except Exception as exc:  # noqa: BLE001 - source failures are isolated.
        counters.targets_failed = 1
        run.error_message = f"adzuna search failed: {exc}"
        return

    counters.targets_ingested = 1
    counters.add_persisted(
        _persist_normalized_jobs(
            normalized_jobs=normalized_jobs,
            run=run,
            job_repo=job_repo,
            query=query,
            role_family_id=role_family_id,
        )
    )


def _ingest_careers_gov(
    *,
    counters: _Counters,
    run: IngestionRun,
    job_repo: JobRepository,
    query: str | None,
    results_per_page: int,
    max_pages: int,
    timeout_seconds: float,
    throttle_seconds: float,
    role_family_id: str | None,
    careers_gov_client: CareersGovClient | None,
) -> None:
    try:
        normalized_jobs = _fetch_careers_gov_jobs(
            query=query,
            results_per_page=results_per_page,
            max_pages=max_pages,
            timeout_seconds=timeout_seconds,
            throttle_seconds=throttle_seconds,
            careers_gov_client=careers_gov_client,
        )
    except Exception as exc:  # noqa: BLE001 - source failures are isolated.
        counters.targets_failed = 1
        run.error_message = f"careers_gov search failed: {exc}"
        return

    counters.targets_ingested = 1
    counters.add_persisted(
        _persist_normalized_jobs(
            normalized_jobs=normalized_jobs,
            run=run,
            job_repo=job_repo,
            query=query,
            role_family_id=role_family_id,
        )
    )


def _ingest_jobstreet(
    *,
    counters: _Counters,
    run: IngestionRun,
    job_repo: JobRepository,
    query: str | None,
    location: str | None,
    max_pages: int,
    site_key: str,
    timeout_seconds: float,
    role_family_id: str | None,
    jobstreet_client: JobstreetClient | None,
) -> None:
    try:
        normalized_jobs = _fetch_jobstreet_jobs(
            query=query,
            location=location,
            max_pages=max_pages,
            site_key=site_key,
            timeout_seconds=timeout_seconds,
            jobstreet_client=jobstreet_client,
        )
    except Exception as exc:  # noqa: BLE001 - source failures are isolated.
        counters.targets_failed = 1
        run.error_message = f"jobstreet search failed: {exc}"
        return

    counters.targets_ingested = 1
    counters.add_persisted(
        _persist_normalized_jobs(
            normalized_jobs=normalized_jobs,
            run=run,
            job_repo=job_repo,
            query=query,
            role_family_id=role_family_id,
        )
    )


def _ingest_target_boards(
    *,
    counters: _Counters,
    run: IngestionRun,
    job_repo: JobRepository,
    handler: SourceHandler | None,
    targets: list[TargetCompany],
    role_family_id: str | None,
) -> None:
    if handler is None:
        raise ValueError("Target-board ingestion requires a source handler")

    for target in targets:
        try:
            postings = handler.client.fetch_postings(target.board_token_or_site)
            normalized_jobs = handler.normalize(target, postings)
        except Exception as exc:  # noqa: BLE001 - source failures are isolated.
            counters.targets_failed += 1
            run.error_message = _append_error(
                run.error_message,
                f"{target.company_name}: {exc}",
            )
            continue

        counters.targets_ingested += 1
        counters.add_persisted(
            _persist_normalized_jobs(
                normalized_jobs=normalized_jobs,
                run=run,
                job_repo=job_repo,
                query=None,
                role_family_id=role_family_id,
            )
        )


def _persist_normalized_jobs(
    *,
    normalized_jobs: list[NormalizedJob],
    run: IngestionRun,
    job_repo: JobRepository,
    query: str | None,
    role_family_id: str | None,
) -> tuple[int, int, int, int, int, set[int]]:
    jobs_seen = 0
    source_listings_upserted = 0
    observations_created = 0
    job_skills_extracted = 0
    duplicate_candidates = 0
    source_listing_ids: set[int] = set()

    for normalized_job in _deduplicate_normalized_jobs(normalized_jobs):
        jobs_seen += 1
        raw_payload = _raw_payload_with_ingestion_metadata(
            normalized_job.raw_payload,
            query=query,
            role_family_id=role_family_id,
        )
        company = job_repo.get_or_create_company(name=normalized_job.company_name)
        job = job_repo.get_or_create_job(
            title=normalized_job.title,
            company=company,
            canonical_url=normalized_job.canonical_url,
            location=normalized_job.location,
            description_text=normalized_job.description_text,
            content_hash=normalized_job.content_hash,
            role_family_id=role_family_id,
            raw_payload=raw_payload,
        )
        listing = job_repo.upsert_source_listing(
            source=normalized_job.source,
            source_job_id=normalized_job.source_job_id,
            ingestion_run=run,
            job=job,
            canonical_url=normalized_job.canonical_url,
            source_url=normalized_job.source_url,
            source_company_name=normalized_job.company_name,
            source_title=normalized_job.title,
            location=normalized_job.location,
            workplace_type=normalized_job.workplace_type,
            description_text=normalized_job.description_text,
            text_quality=normalized_job.text_quality,
            salary_min=normalized_job.salary_min,
            salary_max=normalized_job.salary_max,
            salary_currency=normalized_job.salary_currency,
            salary_interval=normalized_job.salary_interval,
            content_hash=normalized_job.content_hash,
            raw_payload=raw_payload,
            source_updated_at=normalized_job.source_updated_at,
        )
        if listing.id is not None:
            source_listing_ids.add(listing.id)
        source_listings_upserted += 1
        job_repo.record_observation(
            source_listing=listing,
            ingestion_run=run,
            content_hash=normalized_job.content_hash,
            raw_payload=raw_payload,
            source_updated_at=normalized_job.source_updated_at,
        )
        observations_created += 1
        if normalized_job.text_quality == "full_text":
            job_skills_extracted += extract_and_persist_job_skills(
                job_repo.session,
                job,
            )
        duplicate_candidates += _record_duplicate_candidates(job_repo, job)

    return (
        jobs_seen,
        source_listings_upserted,
        observations_created,
        job_skills_extracted,
        duplicate_candidates,
        source_listing_ids,
    )


def _record_missing_query_source_listings(
    *,
    session,
    job_repo: JobRepository,
    run: IngestionRun,
    source: str,
    query: str,
    current_source_listing_ids: set[int] | None,
) -> int:
    current_ids = current_source_listing_ids or set()
    normalized_query = _normalize_query(query)
    missing_observations = 0
    source_listings = session.scalars(
        select(SourceListing).where(SourceListing.source == source)
    ).all()

    for listing in source_listings:
        if listing.id in current_ids:
            continue
        if _listing_ingestion_query(listing) != normalized_query:
            continue
        job_repo.record_observation(
            source_listing=listing,
            ingestion_run=run,
            is_active=False,
            content_hash=listing.content_hash,
            raw_payload=listing.raw_payload,
            source_updated_at=listing.source_updated_at,
        )
        missing_observations += 1
        if (
            _consecutive_inactive_observation_count(session, listing)
            >= CONSECUTIVE_MISSES_TO_CLOSE
            and listing.job is not None
            and _all_job_source_listings_latest_inactive(session, listing.job)
        ):
            listing.job.closed_at = datetime.now(UTC)

    session.flush()
    return missing_observations


def _raw_payload_with_ingestion_metadata(
    raw_payload: dict,
    *,
    query: str | None,
    role_family_id: str | None,
) -> dict:
    metadata = {
        "query": _normalize_query(query),
        "role_family_id": role_family_id,
    }
    return {
        **raw_payload,
        "_roleradar_ingestion": metadata,
    }


def _listing_ingestion_query(listing: SourceListing) -> str | None:
    raw_payload = listing.raw_payload if isinstance(listing.raw_payload, dict) else {}
    metadata = raw_payload.get("_roleradar_ingestion")
    if not isinstance(metadata, dict):
        return None
    return _normalize_query(metadata.get("query"))


def _normalize_query(value: object) -> str | None:
    normalized = " ".join(str(value or "").strip().casefold().split())
    return normalized or None


def _consecutive_inactive_observation_count(
    session,
    listing: SourceListing,
) -> int:
    if listing.id is None:
        return 0
    observations = list(
        session.scalars(
            select(PostingObservation)
            .where(PostingObservation.source_listing_id == listing.id)
            .order_by(
                PostingObservation.observed_at.desc(),
                PostingObservation.id.desc(),
            )
            .limit(CONSECUTIVE_MISSES_TO_CLOSE)
        )
    )
    count = 0
    for observation in observations:
        if observation.is_active:
            break
        count += 1
    return count


def _all_job_source_listings_latest_inactive(session, job: Job) -> bool:
    listings = list(job.source_listings)
    if not listings:
        return False
    for listing in listings:
        if listing.id is None:
            return False
        latest_observation = session.scalar(
            select(PostingObservation)
            .where(PostingObservation.source_listing_id == listing.id)
            .order_by(
                PostingObservation.observed_at.desc(),
                PostingObservation.id.desc(),
            )
            .limit(1)
        )
        if latest_observation is None or latest_observation.is_active:
            return False
    return True


def _deduplicate_normalized_jobs(
    normalized_jobs: Iterable[NormalizedJob],
) -> list[NormalizedJob]:
    """Collapse repeated source identities in one fetched batch before writes."""
    jobs_by_source_identity: dict[tuple[str, str], NormalizedJob] = {}
    for normalized_job in normalized_jobs:
        jobs_by_source_identity[
            (normalized_job.source, normalized_job.source_job_id)
        ] = normalized_job
    return list(jobs_by_source_identity.values())


def _fetch_adzuna_jobs(
    *,
    query: str | None,
    location: str | None,
    country: str,
    results_per_page: int,
    adzuna_app_id: str | None,
    adzuna_app_key: str | None,
    adzuna_client: AdzunaClient | None,
) -> list[NormalizedJob]:
    if not query or not location:
        raise ValueError("Adzuna ingestion requires query and location")
    client = adzuna_client or AdzunaClient(
        app_id=adzuna_app_id or "",
        app_key=adzuna_app_key or "",
    )
    postings = client.search_jobs(
        query=query,
        location=location,
        country=country,
        results_per_page=results_per_page,
    )
    return [normalize_adzuna_posting(posting) for posting in postings]


def _fetch_careers_gov_jobs(
    *,
    query: str | None,
    results_per_page: int,
    max_pages: int,
    timeout_seconds: float,
    throttle_seconds: float,
    careers_gov_client: CareersGovClient | None,
) -> list[NormalizedJob]:
    client = careers_gov_client or CareersGovClient(
        timeout_seconds=timeout_seconds,
        throttle_seconds=throttle_seconds,
    )
    postings = client.search_jobs(
        query=query,
        limit=results_per_page,
        max_pages=max_pages,
    )
    return [normalize_careers_gov_posting(posting) for posting in postings]


def _fetch_jobstreet_jobs(
    *,
    query: str | None,
    location: str | None,
    max_pages: int,
    site_key: str,
    timeout_seconds: float,
    jobstreet_client: JobstreetClient | None,
) -> list[NormalizedJob]:
    if not query or not location:
        raise ValueError("Jobstreet ingestion requires query and location")
    client = jobstreet_client or JobstreetClient(
        site_key=site_key,
        timeout_seconds=timeout_seconds,
    )
    postings = client.search_jobs(
        query=query,
        location=location,
        max_pages=max_pages,
    )
    return [normalize_jobstreet_posting(posting) for posting in postings]


def _targets_for_source(
    *,
    source: str,
    targets_file: str | Path | None,
) -> list[TargetCompany]:
    if source in {"adzuna", "careers_gov", "jobstreet"}:
        return []
    if targets_file is None:
        raise ValueError(f"{source} ingestion requires targets_file")
    return [
        target
        for target in read_target_companies(targets_file)
        if target.enabled and target.source == source
    ]


def _source_handler(
    *,
    source: str,
    lever_client: LeverClient | None,
    greenhouse_client: GreenhouseClient | None,
) -> SourceHandler:
    if source == "lever":
        return SourceHandler(client=lever_client or LeverClient(), source_name=source)
    if source == "greenhouse":
        return SourceHandler(
            client=greenhouse_client or GreenhouseClient(),
            source_name=source,
        )
    raise ValueError(f"Unsupported ingestion source: {source}")


def _record_duplicate_candidates(job_repo: JobRepository, job) -> int:
    count = 0
    for match in job_repo.find_duplicate_candidate_matches(job):
        job_repo.record_duplicate_candidate(
            job=job,
            candidate_job=match.candidate_job,
            match_type=match.match_type,
            score=match.score,
            reason=match.reason,
        )
        count += 1
    return count


def _append_error(existing: str | None, message: str) -> str:
    if not existing:
        return message
    return f"{existing}\n{message}"


def _parse_target(row: dict[str, str]) -> TargetCompany:
    return TargetCompany(
        company_name=(row.get("company_name") or "").strip(),
        source=(row.get("source") or "").strip(),
        board_token_or_site=(row.get("board_token_or_site") or "").strip(),
        enabled=_parse_bool(row.get("enabled", "true")),
        notes=(row.get("notes") or "").strip() or None,
    )


def _parse_bool(value: object) -> bool:
    return str(value or "").strip().casefold() not in {"0", "false", "no", "n"}
