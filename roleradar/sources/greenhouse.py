"""Client for Greenhouse's public job board API."""

from __future__ import annotations

from typing import Any

import requests


GREENHOUSE_JOBS_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


class GreenhouseClient:
    """Small client for public Greenhouse job board postings."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def fetch_postings(self, site: str) -> list[dict[str, Any]]:
        """Fetch all published postings for a Greenhouse board."""
        response = self.session.get(
            GREENHOUSE_JOBS_URL.format(board=site),
            params={"content": "true"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise ValueError("Greenhouse jobs response must contain a jobs list")
        return payload["jobs"]
