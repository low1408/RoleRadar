"""Experimental MyCareersFuture API client for phase 7 ingestion."""

from __future__ import annotations

import time
from typing import Any

import requests
import structlog

API_LINK = "https://api.mycareersfuture.gov.sg/v2/jobs"
MAX_LIMIT = 100


class CareersGovClient:
    """Small client for the MyCareersFuture jobs API.

    The phase-7 plan names this experimental source Careers@Gov; the collector
    uses the MyCareersFuture API endpoint explicitly requested for this phase.
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout_seconds: float = 20.0,
        throttle_seconds: float = 1.0,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout_seconds = timeout_seconds
        self.throttle_seconds = throttle_seconds
        self.logger = structlog.get_logger(__name__)

    def search_jobs(
        self,
        *,
        query: str | None = None,
        limit: int = 20,
        max_pages: int = 1,
    ) -> list[dict[str, Any]]:
        """Search MyCareersFuture job postings using paginated API results."""
        if limit < 1 or limit > MAX_LIMIT:
            raise ValueError(f"MyCareersFuture limit must be between 1 and {MAX_LIMIT}")
        if max_pages < 1:
            raise ValueError("MyCareersFuture max_pages must be at least 1")

        postings: list[dict[str, Any]] = []
        search_query = query or ""

        for page in range(max_pages):
            max_retries = 3
            backoff = 2.0
            for attempt in range(max_retries):
                try:
                    response = self.session.get(
                        API_LINK,
                        params={"limit": limit, "page": page, "search": search_query},
                        headers={"mcf-client": "jobseeker"},
                        timeout=self.timeout_seconds,
                    )
                    response.raise_for_status()
                    break
                except requests.RequestException as exc:
                    if attempt == max_retries - 1:
                        self.logger.warning(
                            "careers_gov.blocked",
                            page=page,
                            query=search_query,
                            error=str(exc),
                        )
                        raise
                    self.logger.info(
                        "careers_gov.retry",
                        page=page,
                        query=search_query,
                        attempt=attempt + 1,
                        error=str(exc),
                    )
                    time.sleep(backoff)
                    backoff *= 2

            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(
                payload.get("results"), list
            ):
                self.logger.warning(
                    "careers_gov.blocked",
                    page=page,
                    query=search_query,
                    error="response missing results list",
                )
                raise ValueError("MyCareersFuture response must contain results list")

            results = payload["results"]
            if not results:
                self.logger.info(
                    "careers_gov.skipped",
                    page=page,
                    query=search_query,
                    reason="empty_results",
                )
                break

            postings.extend(results)
            self.logger.info(
                "careers_gov.changed",
                page=page,
                query=search_query,
                jobs=len(results),
            )

            if len(results) < limit:
                break
            if self.throttle_seconds > 0 and page < max_pages - 1:
                time.sleep(self.throttle_seconds)

        return postings
