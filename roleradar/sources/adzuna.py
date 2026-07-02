"""Client for Adzuna's official job search API."""

from __future__ import annotations

from typing import Any

import requests

ADZUNA_SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"


class AdzunaClient:
    """Small client for Adzuna job search results."""

    def __init__(
        self,
        *,
        app_id: str,
        app_key: str,
        session: requests.Session | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        if not app_id or not app_key:
            raise ValueError("Adzuna app_id and app_key are required")
        self.app_id = app_id
        self.app_key = app_key
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def search_jobs(
        self,
        *,
        query: str,
        location: str,
        country: str = "sg",
        page: int = 1,
        results_per_page: int = 20,
    ) -> list[dict[str, Any]]:
        """Search Adzuna job ads."""
        response = self.session.get(
            ADZUNA_SEARCH_URL.format(country=country, page=page),
            params={
                "app_id": self.app_id,
                "app_key": self.app_key,
                "what": query,
                "where": location,
                "results_per_page": results_per_page,
                "content-type": "application/json",
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(
            payload.get("results"),
            list,
        ):
            raise ValueError("Adzuna search response must contain a results list")
        return payload["results"]
