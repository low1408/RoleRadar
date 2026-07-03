"""Single-posting JobStreet page client."""

from __future__ import annotations

import hashlib
import html
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import requests

JOBSTREET_SOURCE = "jobstreet"
JOBSTREET_ALLOWED_HOSTS = ("jobstreet.com", "jobstreet.com.sg")
JOBSTREET_ALLOWED_HOST_SUFFIXES = (".jobstreet.com", ".jobstreet.com.sg")
JOBSTREET_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


class JobStreetParseError(ValueError):
    """Raised when a JobStreet posting page cannot be converted."""


class JobStreetClient:
    """Fetch and parse one public JobStreet posting URL."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def fetch_posting(self, url: str) -> dict[str, Any]:
        """Fetch one posting URL and return a source payload."""
        posting_url = validate_jobstreet_url(url)
        response = self.session.get(
            posting_url,
            headers=JOBSTREET_HEADERS,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        final_url = getattr(response, "url", None) or posting_url
        return parse_jobstreet_html(response.text, url=final_url)

    def fetch_postings(self, site: str) -> list[dict[str, Any]]:
        """Treat the board token as a single JobStreet posting URL."""
        return [self.fetch_posting(site)]


def validate_jobstreet_url(url: str) -> str:
    """Return a normalized JobStreet URL."""
    normalized_url = url.strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("JobStreet posting URL must use http or https")
    return normalized_url


def parse_jobstreet_html(html_text: str, *, url: str) -> dict[str, Any]:
    """Convert a JobStreet HTML page into a normalized raw source payload."""
    parser = _JobStreetHTMLParser()
    parser.feed(html_text)

    json_ld_objects = _load_json_ld_objects(parser.json_ld_scripts)
    job_posting = _find_job_posting(json_ld_objects)
    meta = parser.meta

    canonical_url = (
        _clean(job_posting.get("url"))
        or _clean(parser.links.get("canonical"))
        or _clean(meta.get("og:url"))
        or url
    )
    title = (
        _clean(job_posting.get("title"))
        or _clean(meta.get("og:title"))
        or _clean(parser.title)
    )
    description_html = _clean(job_posting.get("description"))
    description_text = (
        _html_to_text(description_html)
        or _clean(meta.get("description"))
        or _clean(meta.get("og:description"))
    )
    salary = _salary_parts(job_posting.get("baseSalary"))

    return {
        "source": JOBSTREET_SOURCE,
        "source_job_id": _source_job_id(job_posting, canonical_url),
        "title": title,
        "company_name": _company_name(job_posting),
        "canonical_url": canonical_url,
        "source_url": url,
        "location": _job_location(job_posting),
        "workplace_type": _workplace_type(job_posting),
        "description_html": description_html,
        "description_text": description_text,
        "salary_min": salary["min"],
        "salary_max": salary["max"],
        "salary_currency": salary["currency"],
        "salary_interval": salary["interval"],
        "date_posted": _clean(job_posting.get("datePosted")),
        "valid_through": _clean(job_posting.get("validThrough")),
        "raw_json_ld": job_posting,
        "meta": dict(meta),
    }


class _JobStreetHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.json_ld_scripts: list[str] = []
        self.meta: dict[str, str] = {}
        self.links: dict[str, str] = {}
        self.title = ""
        self._capture_json_ld = False
        self._json_ld_parts: list[str] = []
        self._capture_title = False
        self._title_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {key.lower(): value for key, value in attrs if value is not None}
        tag = tag.lower()
        if tag == "script" and "ld+json" in attributes.get("type", "").lower():
            self._capture_json_ld = True
            self._json_ld_parts = []
            return
        if tag == "title":
            self._capture_title = True
            self._title_parts = []
            return
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            content = attributes.get("content")
            if key and content:
                self.meta[key.lower()] = html.unescape(content).strip()
            return
        if tag == "link":
            rel = attributes.get("rel")
            href = attributes.get("href")
            if rel and href:
                for rel_part in rel.lower().split():
                    self.links[rel_part] = html.unescape(href).strip()

    def handle_data(self, data: str) -> None:
        if self._capture_json_ld:
            self._json_ld_parts.append(data)
        if self._capture_title:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "script" and self._capture_json_ld:
            self.json_ld_scripts.append("".join(self._json_ld_parts).strip())
            self._capture_json_ld = False
            self._json_ld_parts = []
        if tag == "title" and self._capture_title:
            self.title = html.unescape(" ".join(self._title_parts)).strip()
            self._capture_title = False
            self._title_parts = []


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def _load_json_ld_objects(scripts: list[str]) -> list[Any]:
    objects: list[Any] = []
    for script in scripts:
        if not script:
            continue
        try:
            objects.append(json.loads(script))
        except json.JSONDecodeError:
            continue
    return objects


def _find_job_posting(objects: list[Any]) -> dict[str, Any]:
    for candidate in _walk_json(objects):
        if _type_matches(candidate.get("@type"), "JobPosting"):
            return candidate
    return {}


def _walk_json(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        found = [value]
        for child in value.values():
            found.extend(_walk_json(child))
        return found
    if isinstance(value, list):
        found: list[dict[str, Any]] = []
        for child in value:
            found.extend(_walk_json(child))
        return found
    return []


def _type_matches(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value.lower() == expected.lower()
    if isinstance(value, list):
        return any(_type_matches(item, expected) for item in value)
    return False


def _source_job_id(job_posting: dict[str, Any], canonical_url: str) -> str:
    identifier = job_posting.get("identifier")
    if isinstance(identifier, dict):
        source_id = _clean(identifier.get("value")) or _clean(identifier.get("name"))
        if source_id:
            return source_id
    source_id = _clean(identifier)
    if source_id:
        return source_id
    for pattern in (r"/job/(\d+)", r"/jobs/(\d+)", r"[?&]jobId=(\d+)"):
        match = re.search(pattern, canonical_url)
        if match:
            return match.group(1)
    return hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()[:16]


def _company_name(job_posting: dict[str, Any]) -> str | None:
    organization = job_posting.get("hiringOrganization")
    if isinstance(organization, list):
        organization = organization[0] if organization else None
    if isinstance(organization, dict):
        return _clean(organization.get("name"))
    return _clean(organization)


def _job_location(job_posting: dict[str, Any]) -> str | None:
    location = job_posting.get("jobLocation")
    if isinstance(location, list):
        return _join_clean(_job_location({"jobLocation": item}) for item in location)
    if isinstance(location, dict):
        address = location.get("address")
        if isinstance(address, dict):
            return _join_clean(
                [
                    address.get("streetAddress"),
                    address.get("addressLocality"),
                    address.get("addressRegion"),
                    address.get("postalCode"),
                    _country_name(address.get("addressCountry")),
                ]
            )
        return _clean(address) or _clean(location.get("name"))
    return _clean(location)


def _workplace_type(job_posting: dict[str, Any]) -> str | None:
    return _join_clean(
        [
            job_posting.get("employmentType"),
            job_posting.get("jobLocationType"),
        ]
    )


def _salary_parts(base_salary: Any) -> dict[str, float | str | None]:
    if isinstance(base_salary, list):
        base_salary = base_salary[0] if base_salary else None
    if not isinstance(base_salary, dict):
        return {"min": None, "max": None, "currency": None, "interval": None}

    value = base_salary.get("value")
    if isinstance(value, dict):
        min_value = _to_float(value.get("minValue") or value.get("value"))
        max_value = _to_float(value.get("maxValue") or value.get("value"))
        interval = _clean(value.get("unitText"))
    else:
        min_value = _to_float(value)
        max_value = min_value
        interval = None

    return {
        "min": min_value,
        "max": max_value,
        "currency": _clean(base_salary.get("currency")),
        "interval": interval.lower() if interval else None,
    }


def _country_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return _clean(value.get("name")) or _clean(value.get("addressCountry"))
    return _clean(value)


def _html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    parser = _TextExtractor()
    parser.feed(value)
    text = " ".join(parser.parts)
    return text or None


def _join_clean(values: Any) -> str | None:
    if isinstance(values, str):
        return _clean(values)
    parts = [_clean(value) for value in values]
    return ", ".join(part for part in parts if part) or None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
