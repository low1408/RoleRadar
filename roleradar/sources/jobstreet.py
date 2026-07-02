"""Fail-closed policy gate for JobStreet ingestion."""

from __future__ import annotations

JOBSTREET_SOURCE = "jobstreet"
JOBSTREET_ACCESS_DOC_PATH = "docs/jobstreet_access_requirements.md"

PROHIBITED_METHODS = (
    "HTML scraping",
    "browser automation",
    "private GraphQL or internal endpoint calls",
    "session-header spoofing",
    "anti-bot or Cloudflare workarounds",
)


class JobStreetAccessBlockedError(RuntimeError):
    """Raised when JobStreet ingestion is requested before access approval."""


def jobstreet_blocked_message() -> str:
    """Return the user-facing JobStreet access gate message."""
    prohibited = ", ".join(PROHIBITED_METHODS)
    return (
        "JobStreet integration is blocked pending written SEEK/JobStreet "
        "permission or documented API/licensed data access. "
        f"See {JOBSTREET_ACCESS_DOC_PATH}. "
        f"Do not use {prohibited}."
    )


def require_jobstreet_access_approval() -> None:
    """Fail closed until documented JobStreet access is approved."""
    raise JobStreetAccessBlockedError(jobstreet_blocked_message())
