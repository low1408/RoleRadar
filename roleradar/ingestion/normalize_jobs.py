"""Normalize source-specific job payloads into RoleRadar records."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class NormalizedJob:
    """Source-agnostic job representation used by ingestion."""

    source: str
    source_job_id: str
    company_name: str
    title: str
    canonical_url: str | None
    source_url: str | None
    location: str | None
    workplace_type: str | None
    description_text: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_interval: str | None
    content_hash: str | None
    raw_payload: dict[str, Any]
    source_updated_at: datetime | None = None


def normalize_lever_posting(
    *,
    posting: dict[str, Any],
    company_name: str,
    board_token_or_site: str,
) -> NormalizedJob:
    """Normalize one Lever posting payload."""
    source_id = str(posting.get("id") or posting.get("hostedUrl") or posting.get("text"))
    title = _clean(posting.get("text")) or "Untitled role"
    categories = posting.get("categories") if isinstance(posting.get("categories"), dict) else {}
    location = _clean(categories.get("location"))
    workplace_type = _clean(categories.get("commitment"))
    description_text = _lever_description_text(posting)
    salary = posting.get("salaryRange") if isinstance(posting.get("salaryRange"), dict) else {}

    return NormalizedJob(
        source="lever",
        source_job_id=f"{board_token_or_site}:{source_id}",
        company_name=company_name,
        title=title,
        canonical_url=_clean(posting.get("hostedUrl")) or _clean(posting.get("applyUrl")),
        source_url=_clean(posting.get("hostedUrl")) or _clean(posting.get("applyUrl")),
        location=location,
        workplace_type=workplace_type,
        description_text=description_text,
        salary_min=_to_float(salary.get("min")),
        salary_max=_to_float(salary.get("max")),
        salary_currency=_clean(salary.get("currency")) or None,
        salary_interval=_clean(salary.get("interval")) or None,
        content_hash=_content_hash(description_text),
        raw_payload=posting,
        source_updated_at=_lever_timestamp(posting.get("createdAt")),
    )


def _lever_description_text(posting: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for key in ("descriptionPlain", "additionalPlain"):
        value = _clean(posting.get(key))
        if value:
            parts.append(value)

    lists = posting.get("lists")
    if isinstance(lists, list):
        for item in lists:
            if not isinstance(item, dict):
                continue
            heading = _clean(item.get("text"))
            content = _clean(item.get("content"))
            if heading:
                parts.append(heading)
            if content:
                parts.append(content)

    return "\n\n".join(parts) or None


def _content_hash(text: str | None) -> str | None:
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _lever_timestamp(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def _to_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean(value: object) -> str:
    return str(value or "").strip()

