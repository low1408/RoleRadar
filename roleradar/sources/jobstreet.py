"""Client for Jobstreet's chalice-search API."""

from __future__ import annotations

from typing import Any

import requests

JOBSTREET_SEARCH_URL = "https://www.jobstreet.com.sg/api/chalice-search/v4/search"
DEFAULT_SITE_KEY = "SG-Main"
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://sg.jobstreet.com/",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
}


class JobstreetClient:
    """Small client for Jobstreet search result postings."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 20.0,
        site_key: str = DEFAULT_SITE_KEY,
        search_url: str = JOBSTREET_SEARCH_URL,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.site_key = site_key
        self.search_url = search_url

    def search_jobs(
        self,
        *,
        query: str,
        location: str,
        max_pages: int = 1,
        seek_select_all_pages: bool = True,
    ) -> list[dict[str, Any]]:
        """Search Jobstreet postings using the chalice-search endpoint."""
        if max_pages < 1:
            raise ValueError("Jobstreet max_pages must be at least 1")

        postings: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            response = self.session.get(
                self.search_url,
                params={
                    "siteKey": self.site_key,
                    "keywords": query,
                    "where": location,
                    "page": page,
                    "seekSelectAllPages": str(seek_select_all_pages).lower(),
                },
                headers=DEFAULT_HEADERS,
                timeout=self.timeout_seconds,
            )
            _raise_for_blocked_response(response)
            page_postings = _extract_postings(response.json())
            if not page_postings:
                break
            postings.extend(page_postings)

        return postings


def _raise_for_blocked_response(response: requests.Response) -> None:
    if response.status_code == 403 and _looks_like_cloudflare_challenge(response):
        raise RuntimeError(
            "Jobstreet returned a Cloudflare challenge (HTTP 403) instead of JSON. "
            "The chalice-search source is currently blocked for plain HTTP requests."
        )
    response.raise_for_status()


def _looks_like_cloudflare_challenge(response: requests.Response) -> bool:
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        return False
    body = response.text[:2000].casefold()
    return "just a moment" in body or "challenges.cloudflare.com" in body


def _extract_postings(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("Jobstreet search response must be an object")

    candidates = [
        payload.get("data"),
        payload.get("jobs"),
        payload.get("results"),
    ]

    data = payload.get("data")
    if isinstance(data, dict):
        candidates.extend(
            [
                data.get("jobs"),
                data.get("results"),
                data.get("jobCards"),
            ]
        )

    for candidate in candidates:
        if isinstance(candidate, list):
            if not all(isinstance(item, dict) for item in candidate):
                raise ValueError("Jobstreet search postings must be objects")
            return candidate

    raise ValueError("Jobstreet search response must contain postings list")
