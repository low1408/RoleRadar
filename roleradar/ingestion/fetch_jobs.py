"""Job ingestion orchestration."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from roleradar.analytics.skill_matcher import extract_and_persist_job_skills
from roleradar.ingestion.normalize_jobs import NormalizedJob, normalize_lever_posting
from roleradar.sources.lever import LeverClient
from roleradar.storage.database import (
    create_database_engine,
    create_session_factory,
    init_database,
)
from roleradar.storage.repositories import IngestionRunRepository, JobRepository


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
    jobs_seen: int
    source_listings_upserted: int
    observations_created: int
    job_skills_extracted: int


def read_target_companies(file_path: str | Path) -> list[TargetCompany]:
    """Read target companies from a CSV file."""
    path = Path(file_path)
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [_parse_target(row) for row in reader]


def ingest_jobs(
    *,
    database_url: str,
    source: str,
    targets_file: str | Path,
    sqlite_wal: bool = True,
    sqlite_busy_timeout_ms: int = 5000,
    lever_client: LeverClient | None = None,
) -> IngestionResult:
    """Ingest jobs from a supported source."""
    if source != "lever":
        raise ValueError(f"Unsupported ingestion source for Phase 3: {source}")

    targets = [
        target
        for target in read_target_companies(targets_file)
        if target.enabled and target.source == source
    ]
    client = lever_client or LeverClient()

    engine = create_database_engine(
        database_url,
        sqlite_wal=sqlite_wal,
        sqlite_busy_timeout_ms=sqlite_busy_timeout_ms,
    )
    init_database(engine=engine)
    session_factory = create_session_factory(engine)

    jobs_seen = 0
    source_listings_upserted = 0
    observations_created = 0
    job_skills_extracted = 0

    with session_factory() as session:
        run_repo = IngestionRunRepository(session)
        job_repo = JobRepository(session)
        run = run_repo.create(
            source=source,
            parameters={"targets_file": str(targets_file), "target_count": len(targets)},
        )

        for target in targets:
            postings = client.fetch_postings(target.board_token_or_site)
            normalized_jobs = _normalize_source_jobs(target=target, postings=postings)

            for normalized_job in normalized_jobs:
                jobs_seen += 1
                company = job_repo.get_or_create_company(name=normalized_job.company_name)
                job = job_repo.get_or_create_job(
                    title=normalized_job.title,
                    company=company,
                    canonical_url=normalized_job.canonical_url,
                    location=normalized_job.location,
                    description_text=normalized_job.description_text,
                    content_hash=normalized_job.content_hash,
                    raw_payload=normalized_job.raw_payload,
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
                    salary_min=normalized_job.salary_min,
                    salary_max=normalized_job.salary_max,
                    salary_currency=normalized_job.salary_currency,
                    salary_interval=normalized_job.salary_interval,
                    content_hash=normalized_job.content_hash,
                    raw_payload=normalized_job.raw_payload,
                    source_updated_at=normalized_job.source_updated_at,
                )
                source_listings_upserted += 1
                job_repo.record_observation(
                    source_listing=listing,
                    ingestion_run=run,
                    content_hash=normalized_job.content_hash,
                    raw_payload=normalized_job.raw_payload,
                    source_updated_at=normalized_job.source_updated_at,
                )
                observations_created += 1
                job_skills_extracted += extract_and_persist_job_skills(session, job)

        run_repo.complete(run)
        session.commit()

    return IngestionResult(
        source=source,
        targets_seen=len(read_target_companies(targets_file)),
        targets_ingested=len(targets),
        jobs_seen=jobs_seen,
        source_listings_upserted=source_listings_upserted,
        observations_created=observations_created,
        job_skills_extracted=job_skills_extracted,
    )


def _normalize_source_jobs(
    *,
    target: TargetCompany,
    postings: Iterable[dict],
) -> list[NormalizedJob]:
    if target.source != "lever":
        raise ValueError(f"Unsupported target source: {target.source}")

    return [
        normalize_lever_posting(
            posting=posting,
            company_name=target.company_name,
            board_token_or_site=target.board_token_or_site,
        )
        for posting in postings
    ]


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
