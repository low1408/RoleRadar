"""Shared source client interfaces."""

from __future__ import annotations

from typing import Any, Protocol


class JobSourceClient(Protocol):
    """Client capable of fetching raw job postings for one board token."""

    def fetch_postings(self, site: str) -> list[dict[str, Any]]:
        """Fetch published postings for a source site or board token."""
