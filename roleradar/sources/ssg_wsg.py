"""Sync skill taxonomy records from SSG-WSG API responses."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests
from sqlalchemy.orm import Session

from roleradar.storage.models import Skill
from roleradar.storage.repositories import SkillRepository, normalize_text

SSG_WSG_SOURCE = "ssg-wsg"
DEFAULT_TAXONOMY_URL = "https://api.ssg-wsg.gov.sg/skills-framework/v1/skills"


@dataclass(frozen=True)
class SsgWsgTaxonomyRecord:
    """One canonical taxonomy record parsed from an SSG-WSG API response."""

    skill_name: str
    aliases: tuple[str, ...]
    category: str | None = None
    source_taxonomy: str = SSG_WSG_SOURCE
    taxonomy_version: str | None = None
    source_updated_at: datetime | None = None
    raw_payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class TaxonomySyncResult:
    """Summary of a taxonomy sync attempt."""

    source: str
    status: str
    skills_seen: int = 0
    aliases_seen: int = 0
    taxonomy_version: str | None = None
    source_updated_at: datetime | None = None
    message: str | None = None


class SsgWsgTaxonomyClient:
    """Small client for an SSG-WSG taxonomy JSON endpoint."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        taxonomy_url: str = DEFAULT_TAXONOMY_URL,
        session: requests.Session | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("SSG-WSG client_id and client_secret are required")
        self.client_id = client_id
        self.client_secret = client_secret
        self.taxonomy_url = taxonomy_url
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def fetch_taxonomy(self) -> list[SsgWsgTaxonomyRecord]:
        """Fetch and parse taxonomy records from the configured endpoint."""
        response = self.session.get(
            self.taxonomy_url,
            headers={
                "Accept": "application/json",
                "X-IBM-Client-Id": self.client_id,
                "X-IBM-Client-Secret": self.client_secret,
                "X-Client-Id": self.client_id,
                "X-Client-Secret": self.client_secret,
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return parse_taxonomy_response(response.json())


def sync_taxonomy_from_ssg_wsg(
    session: Session,
    *,
    client_id: str | None,
    client_secret: str | None,
    taxonomy_url: str = DEFAULT_TAXONOMY_URL,
    timeout_seconds: float = 20.0,
    client: SsgWsgTaxonomyClient | None = None,
) -> TaxonomySyncResult:
    """Upsert SSG-WSG taxonomy records without replacing local aliases."""
    if not client_id or not client_secret:
        return TaxonomySyncResult(
            source=SSG_WSG_SOURCE,
            status="skipped",
            message=(
                "missing SSG-WSG credentials; set ROLERADAR_SSG_WSG_CLIENT_ID "
                "and ROLERADAR_SSG_WSG_CLIENT_SECRET, or use seed-taxonomy as "
                "the local fallback"
            ),
        )

    taxonomy_client = client or SsgWsgTaxonomyClient(
        client_id=client_id,
        client_secret=client_secret,
        taxonomy_url=taxonomy_url,
        timeout_seconds=timeout_seconds,
    )
    records = taxonomy_client.fetch_taxonomy()
    repository = SkillRepository(session)
    skill_keys: set[tuple[str, str]] = set()
    aliases_seen = 0
    taxonomy_version: str | None = None
    source_updated_at: datetime | None = None

    for record in records:
        skill = repository.get_or_create_skill(
            name=record.skill_name,
            category=record.category,
            source_taxonomy=record.source_taxonomy,
        )
        _apply_taxonomy_metadata(skill, record)
        skill_keys.add((normalize_text(record.skill_name), record.source_taxonomy))
        aliases_seen += _upsert_aliases(repository, skill, record.aliases)
        taxonomy_version = record.taxonomy_version or taxonomy_version
        source_updated_at = _max_datetime(source_updated_at, record.source_updated_at)

    session.flush()
    return TaxonomySyncResult(
        source=SSG_WSG_SOURCE,
        status="completed",
        skills_seen=len(skill_keys),
        aliases_seen=aliases_seen,
        taxonomy_version=taxonomy_version,
        source_updated_at=source_updated_at,
        message="synced SSG-WSG taxonomy",
    )


def parse_taxonomy_response(payload: Any) -> list[SsgWsgTaxonomyRecord]:
    """Parse flexible SSG-WSG taxonomy response shapes into records."""
    items = _extract_items(payload)
    root_version = _first_text(payload, ("version", "taxonomy_version", "release"))
    root_updated_at = _first_text(
        payload,
        ("updated_at", "last_updated", "lastUpdated", "source_updated_at"),
    )
    records: list[SsgWsgTaxonomyRecord] = []

    for item in items:
        if not isinstance(item, dict):
            raise ValueError("SSG-WSG taxonomy items must be objects")

        skill_name = _first_text(
            item,
            (
                "skill_name",
                "skillName",
                "name",
                "title",
                "competency_name",
                "competencyName",
            ),
        )
        if not skill_name:
            raise ValueError("SSG-WSG taxonomy item missing skill_name")

        taxonomy_version = _first_text(
            item,
            ("version", "taxonomy_version", "taxonomyVersion", "release"),
        ) or root_version
        updated_at_value = _first_text(
            item,
            (
                "updated_at",
                "updatedAt",
                "last_updated",
                "lastUpdated",
                "last_modified",
                "lastModified",
                "source_updated_at",
            ),
        ) or root_updated_at

        records.append(
            SsgWsgTaxonomyRecord(
                skill_name=skill_name,
                category=_first_text(
                    item,
                    (
                        "category",
                        "category_name",
                        "categoryName",
                        "skill_category",
                        "skillCategory",
                        "sector",
                    ),
                ),
                aliases=_extract_aliases(item, skill_name),
                taxonomy_version=taxonomy_version,
                source_updated_at=_parse_datetime(updated_at_value),
                raw_payload=item,
            )
        )

    return records


def _apply_taxonomy_metadata(skill: Skill, record: SsgWsgTaxonomyRecord) -> None:
    if record.taxonomy_version:
        skill.taxonomy_version = record.taxonomy_version
    if record.source_updated_at:
        skill.source_updated_at = record.source_updated_at
    skill.updated_at = datetime.now(UTC)


def _upsert_aliases(
    repository: SkillRepository,
    skill: Skill,
    aliases: Iterable[str],
) -> int:
    aliases_seen = 0
    for alias in aliases:
        repository.get_or_create_alias(
            skill=skill,
            alias=alias,
            match_type="literal",
            case_sensitive=False,
        )
        aliases_seen += 1
    return aliases_seen


def _extract_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("SSG-WSG taxonomy response must be an object or list")

    for key in ("skills", "items", "results", "records"):
        value = payload.get(key)
        if isinstance(value, list):
            return value

    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("skills", "items", "results", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return value

    raise ValueError("SSG-WSG taxonomy response missing records list")


def _extract_aliases(item: dict[str, Any], skill_name: str) -> tuple[str, ...]:
    aliases: list[str] = [skill_name]
    for key in (
        "aliases",
        "alias",
        "synonyms",
        "synonym",
        "keywords",
        "keyword",
        "alternate_names",
        "alternateNames",
    ):
        aliases.extend(_text_values(item.get(key)))

    seen: set[str] = set()
    unique_aliases: list[str] = []
    for alias in aliases:
        normalized_alias = normalize_text(alias)
        if not normalized_alias or normalized_alias in seen:
            continue
        seen.add(normalized_alias)
        unique_aliases.append(alias.strip())
    return tuple(unique_aliases)


def _first_text(payload: Any, keys: Iterable[str]) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in keys:
        value = _text_value(payload.get(key))
        if value:
            return value
    return None


def _text_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        separators = [",", ";"]
        values = [value]
        for separator in separators:
            if separator in value:
                values = value.split(separator)
                break
        return [text for item in values if (text := item.strip())]
    if isinstance(value, dict):
        text = _first_text(value, ("name", "title", "value", "label", "alias"))
        return [text] if text else []
    if isinstance(value, Iterable):
        values: list[str] = []
        for item in value:
            values.extend(_text_values(item))
        return values
    text = str(value).strip()
    return [text] if text else []


def _text_value(value: Any) -> str | None:
    values = _text_values(value)
    return values[0] if values else None


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _max_datetime(
    first: datetime | None,
    second: datetime | None,
) -> datetime | None:
    if first is None:
        return second
    if second is None:
        return first
    return max(first, second)
