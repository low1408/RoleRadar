"""Normalize source-specific job payloads into RoleRadar records."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
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
    text_quality: str = "full_text"
    source_updated_at: datetime | None = None


def normalize_lever_posting(
    *,
    posting: dict[str, Any],
    company_name: str,
    board_token_or_site: str,
) -> NormalizedJob:
    """Normalize one Lever posting payload."""
    source_id = str(
        posting.get("id") or posting.get("hostedUrl") or posting.get("text")
    )
    title = _clean(posting.get("text")) or "Untitled role"
    categories = (
        posting.get("categories")
        if isinstance(posting.get("categories"), dict)
        else {}
    )
    location = _clean(categories.get("location"))
    workplace_type = _clean(categories.get("commitment"))
    description_text = _lever_description_text(posting)
    salary = (
        posting.get("salaryRange")
        if isinstance(posting.get("salaryRange"), dict)
        else {}
    )

    return NormalizedJob(
        source="lever",
        source_job_id=f"{board_token_or_site}:{source_id}",
        company_name=company_name,
        title=title,
        canonical_url=(
            _clean(posting.get("hostedUrl")) or _clean(posting.get("applyUrl"))
        ),
        source_url=_clean(posting.get("hostedUrl"))
        or _clean(posting.get("applyUrl")),
        location=location,
        workplace_type=workplace_type,
        description_text=description_text,
        salary_min=_to_float(salary.get("min")),
        salary_max=_to_float(salary.get("max")),
        salary_currency=_clean(salary.get("currency")) or None,
        salary_interval=_clean(salary.get("interval")) or None,
        content_hash=_content_hash(description_text),
        raw_payload=posting,
        text_quality="full_text",
        source_updated_at=_lever_timestamp(posting.get("createdAt")),
    )


def normalize_greenhouse_posting(
    *,
    posting: dict[str, Any],
    company_name: str,
    board_token_or_site: str,
) -> NormalizedJob:
    """Normalize one Greenhouse job board posting payload."""
    source_id = str(
        posting.get("id") or posting.get("absolute_url") or posting.get("title")
    )
    title = _clean(posting.get("title")) or "Untitled role"
    location = _greenhouse_location(posting.get("location"))
    description_text = _html_to_text(_clean(posting.get("content")))
    source_url = _clean(posting.get("absolute_url"))

    return NormalizedJob(
        source="greenhouse",
        source_job_id=f"{board_token_or_site}:{source_id}",
        company_name=company_name,
        title=title,
        canonical_url=source_url,
        source_url=source_url,
        location=location,
        workplace_type=None,
        description_text=description_text,
        salary_min=None,
        salary_max=None,
        salary_currency=None,
        salary_interval=None,
        content_hash=_content_hash(description_text),
        raw_payload=posting,
        text_quality="full_text",
        source_updated_at=_parse_datetime(
            posting.get("updated_at") or posting.get("updatedAt")
        ),
    )


def normalize_adzuna_posting(posting: dict[str, Any]) -> NormalizedJob:
    """Normalize one Adzuna job search result.

    Adzuna search results expose description snippets, not full descriptions.
    """
    source_id = str(
        posting.get("id") or posting.get("redirect_url") or posting.get("title")
    )
    company = (
        posting.get("company") if isinstance(posting.get("company"), dict) else {}
    )
    location = (
        posting.get("location") if isinstance(posting.get("location"), dict) else {}
    )
    description_text = _clean(posting.get("description")) or None

    return NormalizedJob(
        source="adzuna",
        source_job_id=source_id,
        company_name=_clean(company.get("display_name")) or "Unknown company",
        title=_clean(posting.get("title")) or "Untitled role",
        canonical_url=_clean(posting.get("redirect_url")) or None,
        source_url=_clean(posting.get("redirect_url")) or None,
        location=_clean(location.get("display_name")) or None,
        workplace_type=_clean(
            posting.get("contract_time") or posting.get("contract_type")
        )
        or None,
        description_text=description_text,
        salary_min=_to_float(posting.get("salary_min")),
        salary_max=_to_float(posting.get("salary_max")),
        salary_currency=_clean(posting.get("salary_currency")) or "SGD",
        salary_interval=None,
        content_hash=_content_hash(description_text),
        raw_payload={**posting, "text_quality": "snippet"},
        text_quality="snippet",
        source_updated_at=_parse_datetime(posting.get("created")),
    )


def normalize_careers_gov_posting(posting: dict[str, Any]) -> NormalizedJob:
    """Normalize one MyCareersFuture API job result."""
    metadata = _dict_or_empty(posting.get("metadata"))
    company = _dict_or_empty(posting.get("postedCompany"))
    salary = _dict_or_empty(posting.get("salary"))
    salary_type = _dict_or_empty(salary.get("type"))

    source_id = str(
        posting.get("uuid") or metadata.get("jobPostId") or posting.get("title")
    )
    description_text = _html_to_text(_clean(posting.get("description")) or "")
    source_url = _careers_gov_link(posting)
    employment_types = _join_nested_values(
        posting.get("employmentTypes"), "employmentType"
    )

    return NormalizedJob(
        source="careers_gov",
        source_job_id=source_id,
        company_name=_clean(company.get("name")) or "Unknown company",
        title=_clean(posting.get("title")) or "Untitled role",
        canonical_url=source_url,
        source_url=source_url,
        location=(
            _clean(posting.get("placeOfWork"))
            or _clean(posting.get("address"))
            or _clean(posting.get("location"))
            or "Singapore"
        ),
        workplace_type=employment_types or None,
        description_text=description_text,
        salary_min=_to_float(salary.get("minimum")),
        salary_max=_to_float(salary.get("maximum")),
        salary_currency=_clean(salary.get("currency")) or "SGD",
        salary_interval=_clean(salary_type.get("salaryType")) or None,
        content_hash=_content_hash(description_text),
        raw_payload={**posting, "source_api": "mycareersfuture"},
        text_quality="full_text",
        source_updated_at=_parse_datetime(metadata.get("updatedAt")),
    )


def _dict_or_empty(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _careers_gov_link(posting: dict[str, Any]) -> str | None:
    links = _dict_or_empty(posting.get("_links"))
    self_link = _dict_or_empty(links.get("self"))
    return _clean(self_link.get("href")) or None


def _join_nested_values(value: object, key: str) -> str | None:
    if not isinstance(value, list):
        return None

    labels = [
        label
        for item in value
        if isinstance(item, dict)
        for label in [_clean(item.get(key))]
        if label
    ]
    return "; ".join(labels) or None


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


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _greenhouse_location(value: object) -> str | None:
    if isinstance(value, dict):
        return _clean(value.get("name")) or None
    return _clean(value) or None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def _html_to_text(value: str) -> str | None:
    if not value:
        return None
    parser = _TextExtractor()
    parser.feed(value)
    text = " ".join(parser.parts)
    return text or None


def _to_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean(value: object) -> str:
    return str(value or "").strip()
