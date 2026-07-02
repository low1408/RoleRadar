"""Client for Lever's public postings API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


LEVER_POSTINGS_URL = "https://api.lever.co/v0/postings/{site}"


@dataclass(frozen=True)
class LeverTarget:
    """One target company backed by a Lever job board."""

    company_name: str
    board_token_or_site: str


class LeverClient:
    """Small client for public Lever postings."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds

    def fetch_postings(self, site: str) -> list[dict[str, Any]]:
        """Fetch all published postings for a Lever site."""
        response = self.session.get(
            LEVER_POSTINGS_URL.format(site=site),
            params={"mode": "json"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("Lever postings response must be a list")
        return payload

